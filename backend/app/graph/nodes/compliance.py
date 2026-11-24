"""RAG-grounded compliance mapping; never use fine-tuned compliance judgments."""
from app.config import settings
from app.graph.state import PipelineState
from app.llm.client import call_llm_json
from app.retrieval.vector_store import search_knowledge_base


def compliance_node(state: PipelineState) -> PipelineState:
    reqs = state.get("classified_requirements", [])
    if not settings.PHASE2_ENABLED or settings.STUB_MODE:
        mappings = [{"requirement_id": r["id"], "citations": [], "mapping": "Phase 2 disabled", "confidence": 0.0, "escalated": True} for r in reqs]
        state["compliance_mappings"] = mappings
        state.setdefault("escalations", []).extend(f"{m['requirement_id']}: compliance mapping unavailable" for m in mappings)
        state.setdefault("audit_events", []).append({"agent": "compliance", "event": "phase2_disabled", "count": len(mappings)})
        return state

    entry = state.get("slot_state", {}).get("regulatory_jurisdiction", {})
    jurisdiction = entry.get("value") if isinstance(entry, dict) else None
    mappings = []
    for req in reqs:
        query = f"Consumer loan origination compliance controls and regulations for requirement: {req['statement']}"
        try:
            docs = search_knowledge_base(query, top_k=4, jurisdiction=jurisdiction)
        except Exception as exc:
            docs = []
            state.setdefault("audit_events", []).append({"agent": "compliance", "event": "retrieval_error", "requirement_id": req["id"], "error": str(exc)[:300]})
        mapping_text, confidence, citations = "No supported mapping found.", 0.0, []
        if docs:
            evidence = [{k: d.get(k) for k in ("id", "title", "body", "source", "jurisdiction", "effective_date", "version", "similarity")} for d in docs]
            prompt = (
                "Map this consumer-loan software requirement only when supported by supplied evidence. "
                "Never invent a regulation or legal conclusion. Return JSON only: "
                '{"mapping":"brief supported control mapping or unsupported", "confidence":0.0, "citations":[{"doc_id":1,"evidence":"short paraphrase"}], "regulation_labels":["..."], "needs_human_review":true}\n'
                f"Requirement: {req['statement']}\nJurisdiction: {jurisdiction}\nEvidence: {evidence}"
            )
            try:
                result = call_llm_json("You are a retrieval-grounded financial compliance analyst. Cite only supplied evidence.", prompt)
                mapping_text = str(result.get("mapping", "No supported mapping found."))
                confidence = min(float(result.get("confidence", 0.0)), max(d["similarity"] for d in docs))
                doc_by_id = {d["id"]: d for d in docs}
                for citation in result.get("citations", []):
                    doc = doc_by_id.get(citation.get("doc_id")) if isinstance(citation, dict) else None
                    if doc:
                        citations.append({"doc_id": doc["id"], "title": doc["title"], "source": doc["source"], "jurisdiction": doc["jurisdiction"], "effective_date": str(doc["effective_date"]) if doc["effective_date"] else None, "version": doc["version"], "evidence": str(citation.get("evidence", ""))})
                labels = result.get("regulation_labels", [])
                req["applicable_regulations"] = sorted(set(req.get("applicable_regulations", []) + [str(x) for x in labels if x]))
            except Exception as exc:
                state.setdefault("audit_events", []).append({"agent": "compliance", "event": "grounded_analysis_error", "requirement_id": req["id"], "error": str(exc)[:300]})
        confidence = max(0.0, min(1.0, confidence))
        escalated = confidence < settings.COMPLIANCE_MIN_CONFIDENCE or not citations
        mappings.append({"requirement_id": req["id"], "mapping": mapping_text, "citations": citations, "confidence": confidence, "escalated": escalated})
        if escalated:
            state.setdefault("escalations", []).append(f"{req['id']}: compliance mapping has insufficient grounded evidence; compliance/legal review required")
    state["compliance_mappings"] = mappings
    state.setdefault("audit_events", []).append({"agent": "compliance", "event": "rag_mapping", "count": len(mappings), "escalated": sum(m["escalated"] for m in mappings)})
    return state
