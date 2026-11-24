-- Loan Origination Agentic Requirements System
-- Phase 0 schema: sessions, slot state, requirements, audit log, approvals,
-- SDLC recommendations, and a pgvector-backed knowledge base table.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Interview sessions + slot-tracker state
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interview_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    interview_complete BOOLEAN NOT NULL DEFAULT false,
    -- one JSON blob holding the 17-slot state machine:
    -- { "<slot_name>": {"status": "missing|vague|filled", "value": "...", "raw_turns": [...]} }
    slot_state      JSONB NOT NULL DEFAULT '{}'::jsonb,
    pipeline_state  JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS pipeline_state JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS interview_turns (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    turn_index      INT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Requirements (locked-in schema)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS requirements (
    id                      TEXT PRIMARY KEY,        -- e.g. FR-LOAN-001
    session_id              UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    statement               TEXT NOT NULL,
    category                TEXT[] NOT NULL DEFAULT '{}',   -- multi-label
    source_stakeholder      TEXT,
    business_justification  TEXT,
    priority                TEXT CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    dependencies            TEXT[] NOT NULL DEFAULT '{}',
    assumptions             TEXT[] NOT NULL DEFAULT '{}',
    acceptance_criteria     TEXT[] NOT NULL DEFAULT '{}',
    applicable_regulations  TEXT[] NOT NULL DEFAULT '{}',
    risk_level              TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    confidence_score        NUMERIC(4,3) NOT NULL DEFAULT 0.0,
    approval_status         TEXT NOT NULL DEFAULT 'pending'
                              CHECK (approval_status IN ('pending', 'approved', 'rejected', 'regenerate_requested')),
    source_slot             TEXT,        -- traceability back to the originating slot
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_requirements_session ON requirements(session_id);

-- ---------------------------------------------------------------------------
-- SDLC recommendations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sdlc_recommendations (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    -- ranked list: [{"model": "Agile-DevSecOps Hybrid", "score": 0.88}, ...]
    ranked_scores   JSONB NOT NULL DEFAULT '[]'::jsonb,
    narration       TEXT,
    factors_used    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Human-approval records
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_records (
    id              BIGSERIAL PRIMARY KEY,
    requirement_id  TEXT NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    decision        TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'modified', 'regenerate_requested')),
    reviewer        TEXT,
    notes           TEXT,
    modified_statement TEXT,
    modified_acceptance_criteria TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE approval_records ADD COLUMN IF NOT EXISTS modified_statement TEXT;
ALTER TABLE approval_records ADD COLUMN IF NOT EXISTS modified_acceptance_criteria TEXT[];

-- ---------------------------------------------------------------------------
-- Audit log — every agent decision, prompt, retrieval, and approval
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID REFERENCES interview_sessions(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    event_type      TEXT NOT NULL,   -- e.g. "node_start", "node_end", "escalation", "approval"
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Knowledge base (regulations/policies) with pgvector embeddings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_base (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    source          TEXT,
    jurisdiction    TEXT,
    effective_date  DATE,
    version         TEXT,
    embedding       vector(384),   -- fake embeddings in Phase 0; real model in Phase 2
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- one dummy regulation doc so retrieval can be proven end-to-end in Phase 0
INSERT INTO knowledge_base (title, body, source, jurisdiction, version, effective_date)
VALUES (
    'Sample KYC Requirement (placeholder)',
    'Placeholder regulation text: lenders must verify customer identity before disbursing a personal loan. This is a Phase 0 stub document, not real regulatory text.',
    'internal-placeholder',
    'GLOBAL',
    'v0',
    '2020-01-01'
)
ON CONFLICT DO NOTHING;
