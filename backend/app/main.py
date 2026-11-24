from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from langgraph.checkpoint.postgres import PostgresSaver

from app.config import settings
from app.routers import approvals, audit, chat, documents, requirements
from app.db.database import engine
from app.graph.graph import configure_checkpointer

app = FastAPI(
    title="Loan Origination Agentic Requirements System",
    description="Agentic requirements analysis, deterministic SDLC recommendation, generated documents, and human review.",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(requirements.router, prefix="/api")
app.include_router(approvals.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.on_event("startup")
def ensure_phase2_session_state() -> None:
    # Upgrade existing Phase 0 databases without requiring a volume reset.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS pipeline_state JSONB NOT NULL DEFAULT '{}'::jsonb"))
        conn.execute(text("ALTER TABLE approval_records ADD COLUMN IF NOT EXISTS modified_statement TEXT"))
        conn.execute(text("ALTER TABLE approval_records ADD COLUMN IF NOT EXISTS modified_acceptance_criteria TEXT[]"))
    db_uri = settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    checkpoint_context = PostgresSaver.from_conn_string(db_uri)
    checkpointer = checkpoint_context.__enter__()
    checkpointer.setup()
    configure_checkpointer(checkpointer)
    app.state.checkpoint_context = checkpoint_context


@app.on_event("shutdown")
def close_checkpointer() -> None:
    checkpoint_context = getattr(app.state, "checkpoint_context", None)
    if checkpoint_context:
        checkpoint_context.__exit__(None, None, None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "stub_mode": settings.STUB_MODE,
            "phase3_enabled": settings.PHASE3_ENABLED, "phase4_enabled": settings.PHASE4_ENABLED,
            "reviewer_approval_required": settings.REVIEWER_APPROVAL_REQUIRED,
            "optional_analysis_agents_enabled": settings.OPTIONAL_ANALYSIS_AGENTS_ENABLED}
