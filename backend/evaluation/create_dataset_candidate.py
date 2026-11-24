"""Export one completed session as a review-required extraction dataset candidate.

This deliberately does not mark generated requirements as gold labels. Inspect
and correct the candidate before moving it into a training split.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import InterviewSession, InterviewTurn, Requirement


def redact_obvious_identifiers(text: str) -> str:
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text, flags=re.IGNORECASE)
    return re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "[REDACTED_NUMBER]", text)


def create_candidate(session_id: UUID) -> dict[str, Any]:
    with SessionLocal() as db:
        session = db.get(InterviewSession, session_id)
        if session is None:
            raise ValueError(f"Session {session_id} was not found")
        state = session.pipeline_state or {}
        if not state.get("analysis_complete"):
            raise ValueError("Only completed analysis sessions can be exported")

        description = str(state.get("initial_description") or "").strip()
        if not description:
            turns = db.scalars(
                select(InterviewTurn)
                .where(InterviewTurn.session_id == session_id, InterviewTurn.role == "user")
                .order_by(InterviewTurn.turn_index)
            ).all()
            description = "\n\n".join(turn.content.strip() for turn in turns if turn.content.strip())
        if not description:
            raise ValueError("No user-provided description or interview answers were found")

        # Pipeline state is session-scoped and remains authoritative if
        # historical IDs were overwritten by older, non-session-unique IDs.
        requirements = (
            state.get("final_approved_requirements")
            or state.get("classified_requirements")
            or []
        )
        if not requirements:
            requirements = db.scalars(
                select(Requirement).where(Requirement.session_id == session_id)
            ).all()
        target_requirements = []
        for requirement in sorted(
            requirements,
            key=lambda item: item.get("id", "") if isinstance(item, dict) else item.id,
        ):
            get_value = requirement.get if isinstance(requirement, dict) else lambda key, default=None: getattr(requirement, key, default)
            statement = get_value("statement", "")
            source_slot = get_value("source_slot")
            categories = get_value("category") or []
            priority = get_value("priority")
            criteria = get_value("acceptance_criteria") or []
            confidence = get_value("confidence_score") or 0
            target_requirements.append({
                "slot": source_slot or "unmapped",
                "statement": redact_obvious_identifiers(statement),
                "category": list(categories),
                "priority": priority or "medium",
                "acceptance_criteria": [redact_obvious_identifiers(item) for item in criteria],
                "confidence_score": float(confidence),
            })

        slot_state = state.get("slot_state") or {}
        factor_slots = (
            "expected_frequency_of_change",
            "regulatory_audit_criticality",
            "existing_system_integrations",
            "timeline_and_budget",
        )
        factor_inputs = {
            name: str((slot_state.get(name) or {}).get("value") or "")
            for name in factor_slots
        }

        return {
            "scenario_id": "consumer-loan-demo-seed-001",
            "task": "requirement_extraction",
            "review_status": "needs_human_validation",
            "label_provenance": "saved application output; includes reviewer edits",
            "input": {"description": redact_obvious_identifiers(description)},
            "target": {"requirements": target_requirements, "sdlc_factor_inputs": factor_inputs},
            "dataset_note": "Candidate only. Compare every target requirement with the source description; correct omissions, unsupported statements, categories, priorities, and acceptance criteria before training.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", required=True, type=UUID)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/datasets/extraction_candidates.jsonl"),
    )
    parser.add_argument("--stdout", action="store_true", help="Print the candidate instead of writing a file")
    args = parser.parse_args()
    candidate = create_candidate(args.session_id)
    if args.stdout:
        print(json.dumps(candidate, ensure_ascii=False))
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote one review-required candidate to {args.output}")


if __name__ == "__main__":
    main()
