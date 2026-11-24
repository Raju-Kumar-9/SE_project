"""
Env-driven settings for the Loan Origination Agentic Requirements System.

Feature flags allow completed phases to run while later phases remain stubbed.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Mode ---
    STUB_MODE: bool = True
    # Enables real Phase 2 agents while later phases can remain stubbed.
    PHASE2_ENABLED: bool = False
    # When false, skip classification/conflict/clarification/compliance/security/risk.
    OPTIONAL_ANALYSIS_AGENTS_ENABLED: bool = False
    PHASE3_ENABLED: bool = True
    PHASE3_NARRATION_ENABLED: bool = False
    PHASE4_ENABLED: bool = False
    PHASE4_MAX_REVIEW_ROUNDS: int = 2
    # Client-facing runs return analyzed results directly. Enable this only
    # when an internal reviewer approval workflow is explicitly required.
    REVIEWER_APPROVAL_REQUIRED: bool = False
    COMPLIANCE_MIN_CONFIDENCE: float = 0.55
    CLARIFICATION_MAX_ROUNDS: int = 3

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/loan_origination"

    # --- LLM ---
    LLM_PROVIDER: str = "gemini"
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    LLM_MODEL: str = "gemini-3-flash-preview"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TIMEOUT_SECONDS: float = 120.0
    HF_COLAB_ENDPOINT_URL: str = ""

    # --- App ---
    APP_ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


settings = Settings()
