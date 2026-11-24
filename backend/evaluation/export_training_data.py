"""Export only reviewer-approved requirements for Stage 2/3 fine-tuning.

Compliance mappings/citations are deliberately never read or exported. An
optional human-reviewed narration JSONL can be supplied for the narration
task; raw/generated narration is not assumed to be a trusted target.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import InterviewSession, Requirement


def clean_slot_inputs(slot_state: dict[str, Any]) -> dict[str, str]:
    return {
        name: str(item.get("value") or "")
        for name, item in slot_state.items()
        if isinstance(item, dict) and item.get("status") == "filled" and item.get("value")
    }


def redact_obvious_identifiers(text: str) -> str:
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "[REDACTED_NUMBER]", text)
    return text


def export_approved(output: Path, consent_file: Path, narration_labels: Path | None = None) -> int:
    consent_values = json.loads(consent_file.read_text(encoding="utf-8"))
    if not isinstance(consent_values, list) or not all(isinstance(item, str) for item in consent_values):
        raise ValueError("Consent file must contain a JSON array of session ID strings")
    consent_ids = set(consent_values)
    rows: list[dict[str, Any]] = []
    with SessionLocal() as db:
        sessions = db.scalars(select(InterviewSession)).all()
        for session in sessions:
            if str(session.id) not in consent_ids:
                continue
            approved = db.scalars(select(Requirement).where(
                Requirement.session_id == session.id,
                Requirement.approval_status == "approved",
            )).all()
            if not approved:
                continue
            inputs = clean_slot_inputs(session.slot_state or {})
            for requirement in approved:
                source_text = inputs.get(requirement.source_slot or "")
                if not source_text:
                    continue
                source_text = redact_obvious_identifiers(source_text)
                statement = redact_obvious_identifiers(requirement.statement)
                target = {
                    "statement": statement,
                    "source_slot": requirement.source_slot,
                    "category": list(requirement.category or []),
                    "priority": requirement.priority,
                    "acceptance_criteria": list(requirement.acceptance_criteria or []),
                }
                rows.append({"task": "requirement_extraction", "input": {"source_slot": requirement.source_slot, "source_text": source_text}, "target": target})
                rows.append({"task": "classification", "input": {"statement": statement}, "target": {"categories": list(requirement.category or [])}})

            # SDLC narration enters only from separately human-reviewed labels;
            # generated model narration is not treated as ground truth.
    if narration_labels:
        with narration_labels.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                example = json.loads(line)
                if example.get("human_reviewed") is not True:
                    raise ValueError(f"{narration_labels}:{line_number}: narration must be explicitly human_reviewed")
                if "compliance" in json.dumps(example, ensure_ascii=False).casefold():
                    raise ValueError(f"{narration_labels}:{line_number}: compliance content is prohibited in training data")
                rows.append({"task": "sdlc_score_narration", "input": example["input"], "target": example["target"]})

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evaluation/training_data.jsonl"))
    parser.add_argument("--consent-session-ids", type=Path, required=True, help="JSON array of session IDs with explicit data-subject training consent")
    parser.add_argument("--narration-labels", type=Path, help="Optional human-reviewed SDLC narration JSONL")
    args = parser.parse_args()
    count = export_approved(args.output, args.consent_session_ids, args.narration_labels)
    print(f"Wrote {count} reviewed examples to {args.output}")


if __name__ == "__main__":
    main()
