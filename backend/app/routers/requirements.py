from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import get_db
from app.schemas import RequirementOut, RequirementsListResponse

router = APIRouter(tags=["requirements"])


@router.get("/requirements", response_model=RequirementsListResponse)
def list_requirements(session_id: UUID, db: Session = Depends(get_db)) -> RequirementsListResponse:
    session = db.get(models.InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    rows = db.query(models.Requirement).filter_by(session_id=session_id).all()
    one_shot_source = (
        (session.pipeline_state or {}).get("input_mode") == "one_shot"
        and bool((session.pipeline_state or {}).get("initial_description"))
    )
    requirements = []
    for row in rows:
        item = RequirementOut.model_validate(row)
        if not item.source_slot and one_shot_source:
            item.source_slot = "one_shot_description"
        requirements.append(item)
    return RequirementsListResponse(
        session_id=session_id,
        requirements=requirements,
    )
