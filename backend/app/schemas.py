"""
Pydantic request/response models for the FastAPI routers.
Mirrors the locked-in requirement schema from project knowledge.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

Priority = Literal["low", "medium", "high", "critical"]
RiskLevel = Literal["low", "medium", "high", "critical"]
ApprovalStatus = Literal["pending", "approved", "rejected", "regenerate_requested"]
Decision = Literal["approved", "rejected", "modified", "regenerate_requested"]


# --------------------------------------------------------------------------- #
# /chat
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    session_id: UUID | None = None
    message: str = ""
    input_mode: Literal["interview", "one_shot"] = "interview"
    finish_input: bool = False


class RequirementOut(BaseModel):
    id: str
    statement: str
    category: list[str]
    source_stakeholder: str | None = None
    business_justification: str | None = None
    priority: Priority | None = None
    dependencies: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    applicable_regulations: list[str] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    confidence_score: float
    approval_status: ApprovalStatus
    source_slot: str | None = None

    model_config = {"from_attributes": True}


class SdlcRecommendationOut(BaseModel):
    ranked_scores: list[dict[str, Any]]
    narration: str | None = None
    factors_used: dict[str, Any] = Field(default_factory=dict)
    factor_coverage: dict[str, int] = Field(default_factory=dict)
    narration_source: str | None = None

    model_config = {"from_attributes": True}


class PipelineResult(BaseModel):
    """Populated only on the turn that completes the interview."""
    requirements: list[RequirementOut] = Field(default_factory=list)
    sdlc_recommendation: SdlcRecommendationOut | None = None
    validation_notes: list[str] = Field(default_factory=list)
    escalations: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    clarification_flags: list[dict[str, Any]] = Field(default_factory=list)
    compliance_mappings: list[dict[str, Any]] = Field(default_factory=list)
    security_privacy_findings: list[dict[str, Any]] = Field(default_factory=list)
    risk_assessments: list[dict[str, Any]] = Field(default_factory=list)
    generated_documents: list[dict[str, Any]] = Field(default_factory=list)
    approval_routing: list[dict[str, Any]] = Field(default_factory=list)
    approval_pending: bool = False


class ChatResponse(BaseModel):
    session_id: UUID
    assistant_message: str
    interview_complete: bool
    slot_state: dict[str, Any]
    pipeline_result: PipelineResult | None = None


# --------------------------------------------------------------------------- #
# /requirements
# --------------------------------------------------------------------------- #
class RequirementsListResponse(BaseModel):
    session_id: UUID
    requirements: list[RequirementOut]


# --------------------------------------------------------------------------- #
# /approvals
# --------------------------------------------------------------------------- #
class ApprovalRequest(BaseModel):
    requirement_id: str
    decision: Decision
    reviewer: str | None = None
    notes: str | None = None
    modified_statement: str | None = None
    modified_acceptance_criteria: list[str] | None = None


class ApprovalResponse(BaseModel):
    requirement_id: str
    approval_status: ApprovalStatus
    recorded_at: datetime
    approval_pending: bool = False
    analysis_complete: bool = False
    re_review_started: bool = False
    sdlc_recommendation: SdlcRecommendationOut | None = None
    generated_documents: list[dict[str, Any]] = Field(default_factory=list)


class FinalRequirementRevision(BaseModel):
    requirement_id: str
    statement: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)


class FinalDocumentsRefreshRequest(BaseModel):
    revisions: list[FinalRequirementRevision] = Field(default_factory=list)
