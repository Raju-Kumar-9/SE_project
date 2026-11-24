"""
SQLAlchemy models — matches db/init.sql exactly. Keep the two in sync.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    interview_complete = Column(Boolean, nullable=False, default=False)
    slot_state = Column(JSONB, nullable=False, default=dict)
    pipeline_state = Column(JSONB, nullable=False, default=dict)

    turns = relationship("InterviewTurn", back_populates="session", cascade="all, delete-orphan")
    requirements = relationship("Requirement", back_populates="session", cascade="all, delete-orphan")
    sdlc_recommendations = relationship("SdlcRecommendation", back_populates="session", cascade="all, delete-orphan")


class InterviewTurn(Base):
    __tablename__ = "interview_turns"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    turn_index = Column(BigInteger, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="turns")

    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')"),)


class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(String, primary_key=True)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    statement = Column(Text, nullable=False)
    category = Column(ARRAY(String), nullable=False, default=list)
    source_stakeholder = Column(Text)
    business_justification = Column(Text)
    priority = Column(String)
    dependencies = Column(ARRAY(String), nullable=False, default=list)
    assumptions = Column(ARRAY(String), nullable=False, default=list)
    acceptance_criteria = Column(ARRAY(String), nullable=False, default=list)
    applicable_regulations = Column(ARRAY(String), nullable=False, default=list)
    risk_level = Column(String)
    confidence_score = Column(Numeric(4, 3), nullable=False, default=0)
    approval_status = Column(String, nullable=False, default="pending")
    source_slot = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="requirements")
    approvals = relationship("ApprovalRecord", back_populates="requirement", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("priority IN ('low','medium','high','critical')"),
        CheckConstraint("risk_level IN ('low','medium','high','critical')"),
        CheckConstraint("approval_status IN ('pending','approved','rejected','regenerate_requested')"),
    )


class SdlcRecommendation(Base):
    __tablename__ = "sdlc_recommendations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    ranked_scores = Column(JSONB, nullable=False, default=list)
    narration = Column(Text)
    factors_used = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="sdlc_recommendations")


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    requirement_id = Column(String, ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    decision = Column(String, nullable=False)
    reviewer = Column(Text)
    notes = Column(Text)
    modified_statement = Column(Text)
    modified_acceptance_criteria = Column(ARRAY(String))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    requirement = relationship("Requirement", back_populates="approvals")

    __table_args__ = (
        CheckConstraint("decision IN ('approved','rejected','modified','regenerate_requested')"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"))
    agent_name = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class KnowledgeBaseDoc(Base):
    __tablename__ = "knowledge_base"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    source = Column(Text)
    jurisdiction = Column(Text)
    effective_date = Column(Date)
    version = Column(Text)
    # embedding column is managed via raw SQL / pgvector type, not mapped here
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
