from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import get_db
from app.graph.nodes.documentation import documentation_node
from app.graph.nodes.sdlc_selection import _deterministic_narration
from app.graph.sdlc_scoring import score_project
from app.graph.nodes.validation import validation_node
from app.schemas import FinalDocumentsRefreshRequest

router = APIRouter(tags=["documents"])


@router.post("/documents/{session_id}/refresh")
def refresh_final_documents(
    session_id: UUID,
    payload: FinalDocumentsRefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Rebuild final documents from reviewed data; this endpoint makes no LLM calls."""
    session = db.get(models.InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    state = dict(session.pipeline_state or {})
    if not state.get("analysis_complete") or state.get("approval_pending"):
        raise HTTPException(status_code=409, detail="finish reviewer decisions before refreshing final documents")

    rows = db.query(models.Requirement).filter_by(session_id=session_id).all()
    rows_by_id = {row.id: row for row in rows}
    revisions = payload.revisions if payload else []
    revised_ids = set()
    for revision in revisions:
        if revision.requirement_id in revised_ids:
            raise HTTPException(status_code=422, detail="a requirement can be revised only once per request")
        revised_ids.add(revision.requirement_id)
        row = rows_by_id.get(revision.requirement_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"requirement {revision.requirement_id} not found in this session")
        if not revision.statement.strip():
            raise HTTPException(status_code=422, detail="requirement statement cannot be blank")
        if row.approval_status != "approved":
            raise HTTPException(status_code=409, detail="only approved requirements can be amended in the final baseline")
        criteria = [item.strip() for item in revision.acceptance_criteria if item.strip()]
        if not criteria:
            raise HTTPException(status_code=422, detail="at least one acceptance criterion is required")
        row.statement = revision.statement.strip()
        row.acceptance_criteria = criteria
        db.add(models.ApprovalRecord(
            requirement_id=row.id,
            decision="modified",
            reviewer="reviewer",
            notes="Post-final reviewer amendment",
            modified_statement=row.statement,
            modified_acceptance_criteria=criteria,
        ))
        db.add(row)

    saved_requirements = []
    source_is_full_brief = state.get("input_mode") == "one_shot" and bool(state.get("initial_description"))
    for row in rows:
        if not row.source_slot and source_is_full_brief:
            row.source_slot = "one_shot_description"
        saved_requirements.append({
            "id": row.id,
            "statement": row.statement,
            "category": list(row.category or []),
            "source_stakeholder": row.source_stakeholder,
            "business_justification": row.business_justification,
            "priority": row.priority,
            "dependencies": list(row.dependencies or []),
            "assumptions": list(row.assumptions or []),
            "acceptance_criteria": list(row.acceptance_criteria or []),
            "applicable_regulations": list(row.applicable_regulations or []),
            "risk_level": row.risk_level,
            "confidence_score": float(row.confidence_score or 0),
            "approval_status": row.approval_status,
            "source_slot": row.source_slot,
        })
        db.add(row)

    state["classified_requirements"] = saved_requirements
    state["extracted_requirements"] = saved_requirements
    state["final_approved_requirements"] = [
        dict(item) for item in saved_requirements if item["approval_status"] == "approved"
    ]
    if revisions:
        scored, factors = score_project({**state, "classified_requirements": state["final_approved_requirements"]})
        available = sum(1 for item in factors.values() if item["input_available"])
        scored["narration"] = _deterministic_narration(scored["ranked_scores"], factors)
        scored["narration_source"] = "deterministic_template"
        scored["factor_coverage"] = {
            "available": available,
            "total": len(factors),
            "percent": round(available / len(factors) * 100) if factors else 0,
        }
        state["sdlc_recommendation"] = scored
        db.add(models.SdlcRecommendation(
            session_id=session_id,
            ranked_scores=scored["ranked_scores"],
            narration=scored["narration"],
            factors_used={"factor_ratings": factors, "factor_coverage": scored["factor_coverage"],
                          "narration_source": scored["narration_source"]},
        ))
    state["finalizing_approval"] = True
    state["analysis_complete"] = True
    state["approval_pending"] = False
    state["document_revision_requested"] = True
    state = documentation_node(state)
    state = validation_node(state)
    state["analysis_complete"] = True
    state["approval_pending"] = False
    session.pipeline_state = jsonable_encoder(state)
    db.add(models.AuditLog(
        session_id=session_id,
        agent_name="documentation",
        event_type="final_documents_refreshed",
        payload={
            "documents": state.get("generated_documents", []),
            "validation_notes": state.get("validation_notes", []),
            "revised_requirement_ids": sorted(revised_ids),
        },
    ))
    db.commit()
    return {
        "session_id": str(session_id),
        "generated_documents": state.get("generated_documents", []),
        "validation_notes": state.get("validation_notes", []),
        "sdlc_recommendation": state.get("sdlc_recommendation"),
        "revised_requirement_ids": sorted(revised_ids),
        "revised_requirements": [
            {"id": rows_by_id[item].id, "statement": rows_by_id[item].statement,
             "acceptance_criteria": rows_by_id[item].acceptance_criteria}
            for item in sorted(revised_ids)
        ],
        "llm_calls": 0,
    }


@router.get("/documents/{session_id}/{document_type}")
def download_document(session_id: UUID, document_type: Literal["srs", "traceability"], version: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)):
    session = db.get(models.InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    wanted_type = "traceability_matrix" if document_type == "traceability" else "srs"
    candidates = list((session.pipeline_state or {}).get("generated_documents", []))
    if version is not None:
        for event in db.query(models.AuditLog).filter_by(session_id=session_id).all():
            candidates.extend(event.payload.get("generated_documents", []))
            candidates.extend(event.payload.get("documents", []))
    artifact = next((d for d in candidates if d.get("type") == wanted_type and (version is None or d.get("version") == version)), None)
    if artifact is None:
        raise HTTPException(status_code=404, detail="document has not been generated")
    output_path = Path(__file__).resolve().parents[2] / "generated" / str(session_id) / artifact["filename"]
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="generated document file is unavailable")
    return FileResponse(output_path, filename=artifact["filename"], media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
