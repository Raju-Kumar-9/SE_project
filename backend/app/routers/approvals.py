from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.db.database import get_db
from app.graph.graph import get_compiled_graph
from app.schemas import ApprovalRequest, ApprovalResponse

router = APIRouter(tags=["approvals"])

_DECISION_TO_STATUS = {
    "approved": "approved",
    "rejected": "rejected",
    "modified": "approved",
    "regenerate_requested": "regenerate_requested",
}
_FINAL_STATUSES = {"approved", "rejected", "regenerate_requested"}


def _record_audit(db: Session, session_id, event: str, payload: dict) -> None:
    db.add(models.AuditLog(session_id=session_id, agent_name="human_approval", event_type=event, payload=payload))


@router.post("/approvals", response_model=ApprovalResponse)
def record_approval(payload: ApprovalRequest, db: Session = Depends(get_db)) -> ApprovalResponse:
    requirement = db.get(models.Requirement, payload.requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="requirement not found")
    if payload.decision == "modified" and not (payload.modified_statement or "").strip():
        raise HTTPException(status_code=422, detail="modified_statement is required for a modify decision")
    if payload.modified_acceptance_criteria is not None and not any(item.strip() for item in payload.modified_acceptance_criteria):
        raise HTTPException(status_code=422, detail="at least one acceptance criterion is required")
    if requirement.approval_status != "pending":
        raise HTTPException(status_code=409, detail="requirement already has a decision for this review round")
    session = db.get(models.InterviewSession, requirement.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="interview session not found")

    record = models.ApprovalRecord(
        requirement_id=payload.requirement_id,
        decision=payload.decision,
        reviewer=payload.reviewer,
        notes=payload.notes,
        modified_statement=(payload.modified_statement.strip() if payload.modified_statement else None),
        modified_acceptance_criteria=payload.modified_acceptance_criteria,
    )
    db.add(record)
    requirement.approval_status = _DECISION_TO_STATUS[payload.decision]
    if payload.decision == "modified":
        requirement.statement = payload.modified_statement.strip()
        if payload.modified_acceptance_criteria is not None:
            requirement.acceptance_criteria = [
                item.strip() for item in payload.modified_acceptance_criteria if item.strip()
            ]
    db.add(requirement)
    _record_audit(db, session.id, "reviewer_decision", {
        "requirement_id": requirement.id,
        "decision": payload.decision,
        "reviewer": payload.reviewer,
        "notes": payload.notes,
        "modified_statement": payload.modified_statement,
        "modified_acceptance_criteria": payload.modified_acceptance_criteria,
    })
    db.flush()

    state = session.pipeline_state or {}
    review_ids = [row.get("requirement_id") for row in state.get("approval_routing", []) if row.get("requirement_id")]
    if not settings.PHASE4_ENABLED or not state.get("approval_pending") or not review_ids:
        db.commit()
        db.refresh(record)
        return ApprovalResponse(requirement_id=requirement.id, approval_status=requirement.approval_status, recorded_at=record.created_at)

    rows = db.query(models.Requirement).filter(models.Requirement.id.in_(review_ids)).all()
    if len(rows) != len(set(review_ids)):
        raise HTTPException(status_code=409, detail="review queue is incomplete in the database")
    if not all(row.approval_status in _FINAL_STATUSES for row in rows):
        db.commit()
        db.refresh(record)
        return ApprovalResponse(requirement_id=requirement.id, approval_status=requirement.approval_status,
                                recorded_at=record.created_at, approval_pending=True, analysis_complete=False)

    latest_records = (
        db.query(models.ApprovalRecord)
        .filter(models.ApprovalRecord.requirement_id.in_(review_ids))
        .order_by(models.ApprovalRecord.created_at.desc(), models.ApprovalRecord.id.desc())
        .all()
    )
    latest = {}
    for approval in latest_records:
        latest.setdefault(approval.requirement_id, approval)
    resume_decisions = [
        {"requirement_id": req_id, "decision": latest[req_id].decision,
         "modified_statement": latest[req_id].modified_statement,
         "modified_acceptance_criteria": latest[req_id].modified_acceptance_criteria,
         "reviewer": latest[req_id].reviewer,
         "notes": latest[req_id].notes}
        for req_id in review_ids if req_id in latest
    ]
    if len(resume_decisions) != len(set(review_ids)):
        raise HTTPException(status_code=409, detail="every routed requirement needs a reviewer decision")

    config = {"configurable": {"thread_id": str(session.id)}}
    result = get_compiled_graph().invoke(Command(resume=resume_decisions), config=config)
    clean_state = {key: value for key, value in result.items() if key != "__interrupt__"}
    session.pipeline_state = jsonable_encoder(clean_state)

    output_by_id = {r["id"]: r for r in clean_state.get("classified_requirements", [])}
    review_again = bool(clean_state.get("approval_pending"))
    for row in rows:
        output = output_by_id.get(row.id)
        if output and output.get("statement"):
            row.statement = output["statement"]
        if output and output.get("acceptance_criteria") is not None:
            row.acceptance_criteria = output["acceptance_criteria"]
        # Keep completed decisions for unchanged requirements; only rows
        # explicitly returned to pending by the graph need another decision.
        row.approval_status = output.get("approval_status", row.approval_status) if output else row.approval_status
        db.add(row)
    if clean_state.get("finalizing_approval") or any(item["decision"] == "modified" for item in resume_decisions):
        recommendation = clean_state.get("sdlc_recommendation")
        if recommendation:
            db.add(models.SdlcRecommendation(
                session_id=session.id,
                ranked_scores=recommendation["ranked_scores"],
                narration=recommendation.get("narration"),
                factors_used={"factor_ratings": recommendation.get("factors_used", {}),
                              "factor_coverage": recommendation.get("factor_coverage", {}),
                              "narration_source": recommendation.get("narration_source")},
            ))
    _record_audit(db, session.id, "approval_interrupt_resumed", {
        "review_round": clean_state.get("review_round", 1),
        "approval_pending": review_again,
        "analysis_complete": bool(clean_state.get("analysis_complete")),
        "generated_documents": clean_state.get("generated_documents", []),
        "decisions": clean_state.get("approval_decisions", []),
    })
    db.commit()
    db.refresh(record)
    return ApprovalResponse(
        requirement_id=requirement.id,
        approval_status=requirement.approval_status,
        recorded_at=record.created_at,
        approval_pending=review_again,
        analysis_complete=bool(clean_state.get("analysis_complete")),
        re_review_started=review_again,
        sdlc_recommendation=clean_state.get("sdlc_recommendation"),
        generated_documents=clean_state.get("generated_documents", []),
    )
