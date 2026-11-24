# Loan Origination Agentic Requirements System — Phase 0

Multi-agent system that interviews a client about a personal/consumer loan
origination app, extracts structured requirements, and recommends an SDLC
model. The repo contains the Phase 0 skeleton, Phase 1 interview/extraction,
and Phase 2 analysis agents. Feature flags keep later phases stubbed.

## Implementation status

| Area | Status |
|---|---|
| LangGraph orchestration and 17-slot tracker | Implemented |
| Phase 1 interview and requirement extraction | LLM-backed when `STUB_MODE=false` |
| Phase 2 classification, conflict detection, clarification, compliance RAG, security/privacy, risk analysis | LLM/rule-backed when `PHASE2_ENABLED=true` |
| Deterministic SDLC scoring | Implemented in Phase 3; optional LLM narration is off by default |
| Documentation, validation, human approval | Phase 4 uses python-docx, risk-prioritized review, and a durable LangGraph interrupt |
| Evaluation and reviewed training data | Phase 5 JSONL benchmark evaluator and approved-example exporter |
| PostgreSQL persistence, audit trail, React chat/reviewer UI | Implemented |

Phase 2 compliance uses only retrieved evidence, exposes citations and confidence, and escalates weak mappings. Keep this agent RAG-based; never fine-tune it. The clarification loop is persisted between chat requests and capped by `CLARIFICATION_MAX_ROUNDS`.

## Project layout

```
backend/
  app/
    main.py                 FastAPI app + routers
    config.py                Settings (env-driven)
    schemas.py                Pydantic request/response models
    db/
      models.py               SQLAlchemy models (matches locked-in requirement schema)
      database.py              Engine/session
    graph/
      state.py                 Shared LangGraph state (PipelineState) + 17-slot tracker
      graph.py                  Graph builder — wires all 13 agents
      nodes/                    One file per agent (Phase 1/2 implemented; Phases 3 and 4 implemented)
    retrieval/
      vector_store.py          FastEmbed + Pgvector semantic retrieval
    routers/
      chat.py                   Drives one interview turn through the graph
      requirements.py           Read requirements
      approvals.py              Record human decisions
  tests/
    test_graph_smoke.py        Runs a full interview through all 13 agents, no DB/API keys needed
  requirements.txt
  .env.example
frontend/
  src/
    App.jsx
    components/
      ChatInterview.jsx         Chat-style interview UI
      ApprovalDashboard.jsx     Reviewer table (approve/reject/regenerate)
    api.js                      Fetch wrappers for the backend
  package.json
  vite.config.js
db/
  init.sql                    Postgres + pgvector schema, auto-run by docker-compose
docker-compose.yml             Postgres+pgvector container
```

## Running it

### 1. Database

```bash
docker compose up -d
```

This starts Postgres with the `pgvector` extension and runs `db/init.sql`
automatically on first boot.

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # defaults already point at the docker-compose DB
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for the interactive API docs, or
`http://localhost:8000/health` to confirm it's up.

The default provider is the Gemini Developer API free tier. Create a key in [Google AI Studio](https://aistudio.google.com/app/apikey), put it in `GOOGLE_API_KEY` in `backend/.env`, then set `STUB_MODE=false` and restart the backend. The key stays on the backend and should never be added to frontend code or committed. Free-tier limits can change, and Google notes that free-tier content may be used to improve its products; use synthetic demo data rather than real applicant information. The shared LLM client also supports local Ollama (`LLM_PROVIDER=ollama`) if you later want to try CPU inference.

Choose between **Guided interview** and **Describe it in one message** before sending the first message. Both modes continue through requirement extraction, deterministic SDLC scoring, documentation, and reviewer approval. One-shot mode leaves slots missing when the brief does not cover them; the initial requirements are still generated from the full description and should be reviewed for gaps.
### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173`. The chat UI proxies `/api/*` to the backend
on port 8000 (see `vite.config.js`).

### 4. Smoke test (no DB, no frontend needed)

```bash
cd backend
pip install -r requirements.txt
OPTIONAL_ANALYSIS_AGENTS_ENABLED=true PHASE4_ENABLED=false python -m pytest tests/test_graph_smoke.py -v
```

This opts the smoke test into the full secondary-agent graph and disables
the interrupt, then drives a simulated interview through all 17 slots and
asserts the full pipeline runs and produces schema-conformant output. Good first
thing to run after any change to `graph.py` or the node files. (The
compliance node falls back to an empty retrieval result if Postgres isn't
running, so this test genuinely needs no DB up.)

## How a session flows right now

1. Frontend calls `POST /api/chat` with no `session_id` → backend creates an
   `InterviewSession` row, empty slot state.
2. Each user message is one graph invocation. Coordinator checks
   `interview_complete`; while slots remain, it routes to
   `stakeholder_interaction`, which (in stub mode) fills the next targeted
   slot with the raw message and asks the next question off a static bank.
3. When the message that fills the *last* slot arrives, the Stakeholder
   Interaction node refreshes `interview_complete` after applying its slot
   updates. The default route is `requirement_extraction -> sdlc_selection -> documentation -> validation -> human_approval`. Optional secondary analysis runs only when `OPTIONAL_ANALYSIS_AGENTS_ENABLED=true`.
4. Requirements, SDLC recommendations, and the full audit trail are
   persisted; the response includes a `pipeline_result` block the frontend
   uses to populate the reviewer dashboard.
5. Reviewer approves/rejects/requests regeneration per requirement via
   `POST /api/approvals` — this is recorded in `approval_records` and
   reflected onto the requirement's `approval_status`.

## Build sequence

- **Phase 1** complete: stakeholder interview and requirement extraction.
- **Phase 2** implemented and optional: multi-label classification, conflict detection and a durable clarification loop, semantic Pgvector compliance retrieval with citations/confidence/escalation, security/privacy analysis, and transparent risk scoring.
- **Phase 3** implemented: deterministic weighted SDLC scores and optional score-constrained LLM narration.
- **Phase 4** implemented: draft SRS/traceability Word files, validation, durable interrupt/resume, reviewer modification and re-review, final approved-baseline documents after all decisions, and audit UI.
- **Phase 5** implemented: extraction precision/recall/F1, an explicitly labeled hallucination proxy, SDLC top-1/ranking metrics, and export of approved extraction/classification examples. Hand-reviewed SDLC narration labels can be added separately. Compliance mapping and citations are excluded from training data and remain RAG-based.

### Phase 5 evaluation

From `backend/`, create a hand-labeled benchmark and a pipeline prediction JSONL
with matching `scenario_id` values; see `evaluation/FORMAT.md` for the row
format and metric definitions. Then run:

```bash
python -m evaluation.evaluate --gold evaluation/gold.jsonl --predictions evaluation/predictions.jsonl --output evaluation/metrics.json
```

The evaluator reports requirement extraction precision, recall, F1, unmatched
prediction rate (a hallucination proxy that needs human adjudication), SDLC
top-1 accuracy, and mean Kendall rank correlation against hand-scored model
rankings. It requires no API key.

Export fine-tuning examples from requirements that reviewers approved in
PostgreSQL. Add narration examples only after separately reviewing their text
and computed score inputs:

```bash
python -m evaluation.export_training_data --consent-session-ids evaluation/training_consent.json --output evaluation/training_data.jsonl --narration-labels evaluation/reviewed_narration.jsonl
```

Provide the required `--consent-session-ids evaluation/training_consent.json`
argument too; that file must be a JSON array of session UUID strings with
explicit data-subject consent for model training. Reviewer approval alone is
not training consent. The exporter creates extraction and classification
examples only from approved requirements in those sessions, and redacts
obvious email/long-number identifiers. Manually inspect and de-identify the
export before use. It does not export compliance mappings, citations, or
generated SDLC narration. Compliance remains RAG-based and must never enter
fine-tuning.

Populate the knowledge base only with authorized, versioned policy/regulatory material. Use `app.retrieval.vector_store.upsert_document`; FastEmbed downloads `BAAI/bge-small-en-v1.5` weights on first embedding use. The Phase 0 seed row is a placeholder without an embedding and is ignored by retrieval.

## Known Phase 1 simplifications (intentional, not bugs)

- Each LLM call gets exactly one attempt and one fallback (to the
  deterministic Phase 0 behavior) — no retry-with-backoff, no re-prompting
  the model to fix its own malformed JSON.
- No token/cost tracking or rate limiting around the Anthropic calls yet.
- Requirement clarification runs after initial analysis and is capped by `CLARIFICATION_MAX_ROUNDS`.
- Extraction confidence scores are the LLM's own self-reported number, not
  yet calibrated or cross-checked against anything (that groundwork is part
  of the Phase 5 evaluation harness).
