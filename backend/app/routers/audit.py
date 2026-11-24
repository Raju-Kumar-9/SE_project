from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import get_db

router = APIRouter(tags=["audit"])


@router.get("/audit")
def get_audit_trail(session_id: UUID, db: Session = Depends(get_db)) -> dict:
    session = db.get(models.InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    items = []
    for turn in db.query(models.InterviewTurn).filter_by(session_id=session_id).all():
        items.append({"created_at": turn.created_at, "kind": "conversation", "actor": turn.role,
                      "event": "interview_turn", "details": {"turn_index": turn.turn_index, "content": turn.content}})
    for event in db.query(models.AuditLog).filter_by(session_id=session_id).all():
        items.append({"created_at": event.created_at, "kind": "agent", "actor": event.agent_name,
                      "event": event.event_type, "details": event.payload})
    approvals = (
        db.query(models.ApprovalRecord, models.Requirement.statement)
        .join(models.Requirement, models.Requirement.id == models.ApprovalRecord.requirement_id)
        .filter(models.Requirement.session_id == session_id)
        .all()
    )
    for record, statement in approvals:
        items.append({"created_at": record.created_at, "kind": "reviewer", "actor": record.reviewer or "reviewer",
                      "event": record.decision, "details": {"requirement_id": record.requirement_id,
                      "requirement": statement, "notes": record.notes, "modified_statement": record.modified_statement}})
    items.sort(key=lambda item: item["created_at"])
    for item in items:
        item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
    return {"session_id": str(session_id), "events": items}
