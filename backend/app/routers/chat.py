from copy import deepcopy
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import get_db
from app.graph.graph import get_compiled_graph
from app.graph.state import new_slot_state
from app.schemas import ChatRequest, ChatResponse, PipelineResult, RequirementOut, SdlcRecommendationOut

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat_turn(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    if not payload.message.strip() and not payload.finish_input:
        raise HTTPException(status_code=422, detail="message cannot be empty unless finishing the input")

    # --- load or create the session -----------------------------------------
    if payload.session_id is None:
        session = models.InterviewSession(slot_state=new_slot_state())
        db.add(session)
        db.commit()
        db.refresh(session)
    else:
        session = db.get(models.InterviewSession, payload.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if (session.pipeline_state or {}).get("analysis_complete"):
            raise HTTPException(status_code=409, detail="analysis is complete for this session")
        if (session.pipeline_state or {}).get("approval_pending"):
            raise HTTPException(status_code=409, detail="reviewer decisions are pending for this session")

    turn_index = db.query(models.InterviewTurn).filter_by(session_id=session.id).count()
    has_user_message = bool(payload.message.strip())
    if has_user_message:
        db.add(models.InterviewTurn(session_id=session.id, turn_index=turn_index, role="user", content=payload.message))

    # --- run one graph invocation --------------------------------------------
    persisted_state = session.pipeline_state or {}
    input_mode = persisted_state.get("input_mode", payload.input_mode)
    previous_description = persisted_state.get("initial_description", "")
    accumulated_description = "\n\n".join(
        part for part in (previous_description, payload.message.strip()) if part
    )
    state = {
        **persisted_state,
        "session_id": session.id,
        "user_message": payload.message,
        "input_mode": input_mode,
        "initial_description": accumulated_description,
        "finish_input": payload.finish_input,
        # pipeline_state is replaced as a whole every turn and is therefore
        # authoritative if an older run failed to persist nested JSONB edits
        # to the separate slot_state column.
        "slot_state": deepcopy(persisted_state.get("slot_state") or session.slot_state),
        "turn_index": turn_index,
        "interview_complete": session.interview_complete,
        "audit_events": [],
    }
    result_state = get_compiled_graph().invoke(
        state,
        config={"configurable": {"thread_id": str(session.id)}},
    )

    # --- persist slot state / completion -------------------------------------
    # JSONB columns do not track nested in-place edits. The graph may mutate
    # the same dict loaded from the ORM, so assign a distinct object to ensure
    # SQLAlchemy persists each interview turn's slot updates.
    session.slot_state = deepcopy(result_state["slot_state"])
    session.interview_complete = result_state.get("interview_complete", False)
    clean_state = {key: value for key, value in result_state.items() if key != "__interrupt__"}
    session.pipeline_state = jsonable_encoder(clean_state)
    db.add(session)

    assistant_message = result_state.get("assistant_message", "")
    db.add(
        models.InterviewTurn(
            session_id=session.id,
            turn_index=turn_index + (1 if has_user_message else 0),
            role="assistant",
            content=assistant_message,
        )
    )

    for event in result_state.get("audit_events", []):
        db.add(
            models.AuditLog(
                session_id=session.id,
                agent_name=event.get("agent", "unknown"),
                event_type=event.get("event", "unknown"),
                payload=event,
            )
        )

    pipeline_result = None
    if (result_state.get("approval_pending") or result_state.get("analysis_complete")) and result_state.get("classified_requirements"):
        for req in result_state["classified_requirements"]:
            db_req = models.Requirement(session_id=session.id, **req)
            db.merge(db_req)

        rec = result_state.get("sdlc_recommendation")
        sdlc_out = None
        if rec:
            db.add(
                models.SdlcRecommendation(
                    session_id=session.id,
                    ranked_scores=rec["ranked_scores"],
                    narration=rec.get("narration"),
                    factors_used={
                        "factor_ratings": rec.get("factors_used", {}),
                        "factor_coverage": rec.get("factor_coverage", {}),
                        "narration_source": rec.get("narration_source"),
                    },
                )
            )
            sdlc_out = SdlcRecommendationOut(**rec)

        pipeline_result = PipelineResult(
            requirements=[RequirementOut(**req) for req in result_state["classified_requirements"]],
            sdlc_recommendation=sdlc_out,
            validation_notes=result_state.get("validation_notes", []),
            escalations=result_state.get("escalations", []),
            conflicts=result_state.get("conflicts", []),
            clarification_flags=result_state.get("clarification_flags", []),
            compliance_mappings=result_state.get("compliance_mappings", []),
            security_privacy_findings=result_state.get("security_privacy_findings", []),
            risk_assessments=result_state.get("risk_assessments", []),
            generated_documents=result_state.get("generated_documents", []),
            approval_routing=result_state.get("approval_routing", []),
            approval_pending=result_state.get("approval_pending", False),
        )

    db.commit()

    return ChatResponse(
        session_id=session.id,
        assistant_message=assistant_message,
        interview_complete=session.interview_complete,
        slot_state=session.slot_state,
        pipeline_result=pipeline_result,
    )
