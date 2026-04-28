"""
src/storage/models.py — Modèles SQLAlchemy 2.0 (async).

4 tables :
- opportunities : toutes les opportunités détectées et leur cycle de vie
- runs : log des exécutions hebdo (audit + monitoring)
- feedback : décisions Go/No-Go renvoyées par UGFS
- scoring_weights : poids du scoring, versionnés pour la boucle d'apprentissage
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Dimension des embeddings Voyage `voyage-3-lite`
EMBEDDING_DIM = 512


class Base(DeclarativeBase):
    """Base class pour tous les modèles."""


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Métadonnées source
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(2000))
    source: Mapped[str] = mapped_column(String(100))
    source_kind: Mapped[str] = mapped_column(String(50))

    # Données analysées
    summary_executive: Mapped[str | None] = mapped_column(Text)
    opportunity_type: Mapped[str | None] = mapped_column(String(50))
    theme: Mapped[str | None] = mapped_column(String(50))
    geographies: Mapped[list[str] | None] = mapped_column(JSON)
    sectors: Mapped[list[str] | None] = mapped_column(JSON)
    eligibility_summary: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    deadline_text_raw: Mapped[str | None] = mapped_column(String(200))
    ticket_size_usd: Mapped[int | None] = mapped_column(BigInteger)
    languages: Mapped[list[str] | None] = mapped_column(JSON)
    why_interesting: Mapped[str | None] = mapped_column(Text)
    preliminary_decision: Mapped[str | None] = mapped_column(String(20))
    decision_rationale: Mapped[str | None] = mapped_column(Text)
    partners_mentioned: Mapped[list[str] | None] = mapped_column(JSON)
    vehicle_match: Mapped[str | None] = mapped_column(String(50))
    submission_url: Mapped[str | None] = mapped_column(String(2000))

    # Scoring
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    similarity_to_past_go: Mapped[float] = mapped_column(Float, default=0.0)
    similar_past_opportunities: Mapped[list[str] | None] = mapped_column(JSON)

    # Cycle de vie
    status: Mapped[str] = mapped_column(String(30), default="DETECTED", index=True)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Embedding pour la similarité (le LLM résumé est embedded)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    # Timestamps
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # Décision client (renseignée via feedback)
    client_decision: Mapped[str | None] = mapped_column(String(20))     # GO / NO_GO / BORDERLINE
    client_reason: Mapped[str | None] = mapped_column(Text)
    client_decided_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relations
    feedbacks: Mapped[list["Feedback"]] = relationship(back_populates="opportunity", cascade="all,delete")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")  # RUNNING / OK / FAILED

    sources_attempted: Mapped[int] = mapped_column(Integer, default=0)
    sources_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    raw_collected: Mapped[int] = mapped_column(Integer, default=0)
    new_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    urgent_alerts: Mapped[int] = mapped_column(Integer, default=0)
    excel_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(20))                    # GO / NO_GO / BORDERLINE
    reason: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[str | None] = mapped_column(String(200))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    opportunity: Mapped[Opportunity] = relationship(back_populates="feedbacks")


class ScoringWeights(Base):
    __tablename__ = "scoring_weights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON)
    based_on_n_feedbacks: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(50), default="initial")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    __table_args__ = (UniqueConstraint("version", name="uq_weights_version"),)


# ============================================================
# Auth & Audit (dashboard web)
# ============================================================

class User(Base):
    """Utilisateur du dashboard web."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))     # bcrypt
    role: Mapped[str] = mapped_column(String(20), default="analyst")  # admin / analyst / viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    """Trace des événements de sécurité et de décision."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_email: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(50), index=True)
    # Actions: LOGIN_OK, LOGIN_FAIL, LOGOUT, DECISION_GO, DECISION_NO_GO,
    # DECISION_BORDERLINE, EXCEL_UPLOAD, RUN_TRIGGERED, USER_CREATED
    resource_type: Mapped[str | None] = mapped_column(String(50))    # opportunity / user / run
    resource_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(50))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
