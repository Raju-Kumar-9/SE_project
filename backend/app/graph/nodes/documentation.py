"""Generate SRS and requirement traceability artifacts as Word documents."""
from pathlib import Path

from app.config import settings
from app.graph.sdlc_scoring import FACTOR_WEIGHTS
from app.graph.state import PipelineState


def _add_field(document, label: str, value) -> None:
    paragraph = document.add_paragraph()
    paragraph.add_run(f"{label}: ").bold = True
    if isinstance(value, (list, tuple)):
        paragraph.add_run("; ".join(str(item) for item in value) or "Not specified")
    else:
        paragraph.add_run(str(value) if value not in (None, "") else "Not specified")


def documentation_node(state: PipelineState) -> PipelineState:
    if not settings.PHASE4_ENABLED:
        state["generated_documents"] = [{"type": "srs_placeholder", "requirement_count": len(state.get("classified_requirements", [])), "note": "Phase 4 disabled"}]
        state.setdefault("audit_events", []).append({"agent": "documentation", "event": "phase4_disabled"})
        return state

    from docx import Document

    session_id = str(state.get("session_id", "session"))
    output_dir = Path(__file__).resolve().parents[3] / "generated" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    is_final = bool(state.get("finalizing_approval"))
    review_required = bool(state.get("reviewer_approval_required", settings.REVIEWER_APPROVAL_REQUIRED))
    document_version = max(1, int(state.get("review_round", 1)) + int(is_final))
    existing_versions = [
        int(item.get("version", 0))
        for item in state.get("generated_documents", [])
        if isinstance(item, dict) and item.get("version") is not None
    ]
    if state.get("document_revision_requested") and existing_versions:
        document_version = max(document_version, max(existing_versions) + 1)
    all_requirements = state.get("classified_requirements", [])
    if state.get("input_mode") == "one_shot" and state.get("initial_description"):
        for req in all_requirements:
            if not req.get("source_slot"):
                req["source_slot"] = "one_shot_description"
    requirements = state.get("final_approved_requirements", []) if is_final else all_requirements
    if state.get("input_mode") == "one_shot" and state.get("initial_description"):
        for req in requirements:
            if not req.get("source_slot"):
                req["source_slot"] = "one_shot_description"
    decisions_by_id = {
        item.get("requirement_id"): item
        for item in state.get("approval_decisions", [])
        if item.get("requirement_id")
    }
    slots = state.get("slot_state", {})

    srs = Document()
    srs.add_heading("Software Requirements Specification", 0)
    srs.add_paragraph("Personal / Consumer Loan Origination Application", style="Subtitle")
    srs.add_paragraph(f"Session: {session_id}")
    if is_final and not review_required:
        srs.add_paragraph("Status: Analysis output generated from the client description")
    else:
        srs.add_paragraph("Status: Final approved baseline" if is_final else "Status: Draft for reviewer approval")
    srs.add_heading("1. Project scope", level=1)
    scope = slots.get("business_goal_and_target_customers", {}).get("value", "")
    srs.add_paragraph(scope or "Scope to be confirmed by the project stakeholders.")
    srs.add_heading("2. Stakeholder and system context", level=1)
    for slot_name, heading in (("user_roles", "User roles"), ("application_flow", "Application flow"), ("existing_system_integrations", "Existing integrations")):
        _add_field(srs, heading, slots.get(slot_name, {}).get("value"))
    srs.add_heading("3. Requirements", level=1)
    for req in requirements:
        srs.add_heading(req.get("id", "Requirement"), level=2)
        srs.add_paragraph(req.get("statement", ""))
        for key, label in (("category", "Categories"), ("source_slot", "Source slot"), ("source_stakeholder", "Source stakeholder"),
                           ("business_justification", "Business justification"), ("priority", "Priority"),
                           ("dependencies", "Dependencies"), ("assumptions", "Assumptions"),
                           ("acceptance_criteria", "Acceptance criteria"), ("applicable_regulations", "Applicable regulations"),
                           ("risk_level", "Risk level"), ("confidence_score", "Extraction confidence")):
            _add_field(srs, label, req.get(key))
        if review_required or not is_final:
            _add_field(srs, "Reviewer status", req.get("approval_status"))
    if is_final:
        rejected_count = sum(1 for req in all_requirements if req.get("approval_status") == "rejected")
        if review_required:
            srs.add_paragraph(
                f"Final baseline: {len(requirements)} approved requirement(s); "
                f"{rejected_count} rejected requirement(s) are recorded in the traceability matrix."
            )
        else:
            srs.add_paragraph(
                f"Analysis output: {len(requirements)} extracted requirement(s). "
                "These describe the client's requested product; they are not approvals or commitments to implement it."
            )
    srs.add_heading("4. SDLC recommendation", level=1)
    recommendation = state.get("sdlc_recommendation", {})
    ranked_scores = recommendation.get("ranked_scores", [])
    factor_coverage = recommendation.get("factor_coverage", {})
    factors_used = recommendation.get("factors_used", {})
    srs.add_paragraph(
        "Factor inputs marked available: "
        f"{factor_coverage.get('available', 0)}/{factor_coverage.get('total', len(FACTOR_WEIGHTS))}. "
        "Percentages are normalized weighted suitability scores, not probabilities or model confidence. "
        "Available means the factor was informed by interview data or derived from requirements; it does not necessarily mean a stakeholder supplied a direct rating."
    )
    if ranked_scores:
        ranking_table = srs.add_table(rows=1, cols=3)
        ranking_table.style = "Light Shading Accent 1"
        for cell, label in zip(ranking_table.rows[0].cells, ("Rank", "SDLC model", "Suitability score")):
            cell.text = label
        for index, row in enumerate(ranked_scores, start=1):
            cells = ranking_table.add_row().cells
            cells[0].text = str(index)
            cells[1].text = str(row.get("model", ""))
            cells[2].text = f"{row.get('score_percent', round(row.get('score', 0) * 100, 1))}%"
    srs.add_paragraph(recommendation.get("narration", ""))
    if factors_used:
        srs.add_heading("Scoring factors and evidence", level=2)
        srs.add_paragraph(
            "For each model, the scorer computes 100 x sum(weight x (5 - absolute difference "
            "between the project rating and model profile rating)) / (5 x sum of weights). "
            "It then ranks the resulting weighted suitability percentages. "
            "Rows marked Default use a fallback rating because the source input was missing."
        )
        factor_table = srs.add_table(rows=1, cols=4)
        factor_table.style = "Light Shading Accent 1"
        for cell, label in zip(factor_table.rows[0].cells, ("Factor", "Rating", "Weight", "Input basis and evidence")):
            cell.text = label
        for factor_name, factor in factors_used.items():
            cells = factor_table.add_row().cells
            cells[0].text = factor_name.replace("_", " ").title()
            cells[1].text = f"{factor.get('rating', '—')}/5"
            cells[2].text = str(FACTOR_WEIGHTS.get(factor_name, "—"))
            availability = "Available (direct or derived)" if factor.get("input_available") else "Default (source input missing)"
            basis = factor.get("basis", "basis not recorded")
            rationale = factor.get("rationale", "")
            cells[3].text = f"{availability}; {basis}. {rationale}".strip()
    if state.get("compliance_mappings"):
        srs.add_heading("5. Compliance mappings", level=1)
    for mapping in state.get("compliance_mappings", []):
        srs.add_heading(mapping.get("requirement_id", "Mapping"), level=2)
        srs.add_paragraph(mapping.get("mapping", "No mapping supplied."))
        for citation in mapping.get("citations", []):
            _add_field(srs, "Evidence source", f"{citation.get('title')} — {citation.get('source')} — {citation.get('version')}")
    srs_path = output_dir / f"SRS-v{document_version}.docx"
    srs.save(srs_path)

    trace = Document()
    trace.add_heading("Requirements Traceability Matrix", 0)
    trace.add_paragraph(f"Session: {session_id}")
    if is_final and not review_required:
        trace.add_paragraph("Status: Extracted analysis output; client approval is not part of this workflow")
    else:
        trace.add_paragraph("Status: Final disposition recorded" if is_final else "Status: Draft for reviewer approval")
    table = trace.add_table(rows=1, cols=9)
    table.style = "Light Shading Accent 1"
    status_header = "Analysis status" if not review_required else "Approval status"
    headers = ("Requirement ID", "Requirement", "Source slot", "Source interview answer", "Acceptance criteria", status_header, "Reviewer decision", "Reviewer", "Review notes")
    for cell, title in zip(table.rows[0].cells, headers):
        cell.text = title
    for req in all_requirements:
        slot = slots.get(req.get("source_slot"), {})
        source_text = "\n".join(slot.get("raw_turns", [])) or slot.get("value", "")
        if not source_text and state.get("input_mode") == "one_shot":
            source_text = state.get("initial_description", "")
        cells = table.add_row().cells
        review = decisions_by_id.get(req.get("id"), {})
        values = (
            req.get("id", ""), req.get("statement", ""), req.get("source_slot", ""), source_text,
            "\n".join(req.get("acceptance_criteria", [])),
            ("Extracted" if req.get("approval_status") == "pending" else req.get("approval_status", "Extracted")) if not review_required else req.get("approval_status", "pending"),
            review.get("decision", "Not applicable" if not review_required else "Not reviewed"),
            review.get("reviewer", ""), review.get("notes", ""),
        )
        for cell, value in zip(cells, values):
            cell.text = str(value or "Not captured")
    trace_path = output_dir / f"Traceability-Matrix-v{document_version}.docx"
    trace.save(trace_path)

    srs_title = "Final SRS" if is_final else "Software Requirements Specification (Draft)"
    trace_title = "Final Traceability Matrix" if is_final else "Requirements Traceability Matrix (Draft)"
    state["generated_documents"] = [
        {"type": "srs", "title": srs_title, "filename": srs_path.name, "version": document_version, "stage": "final" if is_final else "draft", "download_url": f"/api/documents/{session_id}/srs?version={document_version}", "requirement_count": len(requirements)},
        {"type": "traceability_matrix", "title": trace_title, "filename": trace_path.name, "version": document_version, "stage": "final" if is_final else "draft", "download_url": f"/api/documents/{session_id}/traceability?version={document_version}", "requirement_count": len(all_requirements)},
    ]
    state["document_revision_requested"] = False
    state.setdefault("audit_events", []).append({"agent": "documentation", "event": "documents_finalized" if is_final else "documents_generated", "documents": state["generated_documents"], "requirement_count": len(requirements)})
    return state
