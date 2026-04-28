"""
src/storage/repository.py — Couche d'accès données (repository pattern).

Toutes les requêtes DB passent par ici. Cela isole le métier du SQL et
permet de tester facilement (mock du repository, pas du SQL).
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import ScoredOpportunity
from src.config.logger import get_logger

from .models import Feedback, Opportunity, Run, ScoringWeights

logger = get_logger(__name__)


# ============================================================
# Helpers de fingerprint (déduplication)
# ============================================================

def compute_fingerprint(title: str, url: str, deadline: date | None = None) -> str:
    """
    Fingerprint sémantique pour dédupliquer les opportunités.

    On normalise titre + URL canonique + deadline. Une même opportunité
    re-scrapée la semaine suivante doit produire le même fingerprint.
    """
    normalized_title = " ".join(title.lower().split())
    canonical_url = url.split("?")[0].rstrip("/").lower()
    deadline_str = deadline.isoformat() if deadline else "rolling"
    payload = f"{normalized_title}||{canonical_url}||{deadline_str}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ============================================================
# Opportunity repo
# ============================================================

class OpportunityRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists(self, fingerprint: str) -> bool:
        stmt = select(Opportunity.id).where(Opportunity.fingerprint == fingerprint)
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def get_by_fingerprint(self, fingerprint: str) -> Opportunity | None:
        stmt = select(Opportunity).where(Opportunity.fingerprint == fingerprint)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_scored(self, scored: ScoredOpportunity) -> Opportunity:
        """Insère ou met à jour une opportunité scorée."""
        existing = await self.get_by_fingerprint(scored.fingerprint)
        if existing:
            # Update : on rafraîchit deadline + last_seen + score (au cas où)
            existing.last_seen_at = datetime.utcnow()
            existing.score = scored.score
            existing.is_urgent = scored.is_urgent
            existing.deadline = scored.analyzed.deadline
            return existing

        opp = Opportunity(
            fingerprint=scored.fingerprint,
            title=scored.raw.title,
            url=scored.raw.url,
            source=scored.raw.source,
            source_kind=scored.raw.source_kind.value,
            summary_executive=scored.analyzed.summary_executive,
            opportunity_type=scored.analyzed.opportunity_type.value,
            theme=scored.analyzed.theme.value,
            geographies=scored.analyzed.geographies,
            sectors=scored.analyzed.sectors,
            eligibility_summary=scored.analyzed.eligibility_summary,
            deadline=scored.analyzed.deadline,
            deadline_text_raw=scored.analyzed.deadline_text_raw,
            ticket_size_usd=scored.analyzed.ticket_size_usd,
            languages=scored.analyzed.languages,
            why_interesting=scored.analyzed.why_interesting,
            preliminary_decision=scored.analyzed.preliminary_decision.value,
            decision_rationale=scored.analyzed.decision_rationale,
            partners_mentioned=scored.analyzed.partners_mentioned,
            vehicle_match=scored.analyzed.vehicle_match,
            submission_url=scored.analyzed.submission_url,
            score=scored.score,
            score_breakdown=scored.score_breakdown,
            similarity_to_past_go=scored.similarity_to_past_go,
            similar_past_opportunities=scored.similar_past_opportunities,
            status=scored.status,
            is_urgent=scored.is_urgent,
        )
        self.session.add(opp)
        await self.session.flush()
        return opp

    async def add_embedding(self, opportunity_id: int, embedding: list[float]) -> None:
        stmt = (
            update(Opportunity)
            .where(Opportunity.id == opportunity_id)
            .values(embedding=embedding)
        )
        await self.session.execute(stmt)

    async def list_recent(
        self,
        days: int = 7,
        only_open: bool = True,
        min_score: int = 0,
    ) -> Sequence[Opportunity]:
        """Opportunités détectées dans les N derniers jours."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(Opportunity)
            .where(Opportunity.discovered_at >= cutoff)
            .where(Opportunity.score >= min_score)
            .order_by(Opportunity.score.desc())
        )
        if only_open:
            today = date.today()
            stmt = stmt.where((Opportunity.deadline >= today) | (Opportunity.deadline.is_(None)))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_urgent_unprocessed(self) -> Sequence[Opportunity]:
        """Opportunités urgentes (deadline ≤ 7j) non encore traitées par UGFS."""
        cutoff = date.today() + timedelta(days=7)
        stmt = (
            select(Opportunity)
            .where(Opportunity.is_urgent.is_(True))
            .where(Opportunity.deadline.isnot(None))
            .where(Opportunity.deadline <= cutoff)
            .where(Opportunity.deadline >= date.today())
            .where(Opportunity.client_decision.is_(None))
            .order_by(Opportunity.deadline.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_similar(
        self,
        embedding: list[float],
        threshold: float = 0.85,
        limit: int = 5,
        decision_filter: str | None = "GO",
    ) -> Sequence[tuple[Opportunity, float]]:
        """
        Recherche les opportunités similaires (cosine sim >= threshold).

        Retourne [(opp, similarity)]. Permet de filtrer par décision client
        (ex: ne renvoyer que les Go passés) pour la calibration du scoring.
        """
        # cosine_distance = 1 - cosine_similarity ; pgvector utilise <=>
        from sqlalchemy import literal
        stmt = (
            select(Opportunity, (1 - Opportunity.embedding.cosine_distance(embedding)).label("sim"))
            .where(Opportunity.embedding.isnot(None))
            .order_by(Opportunity.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        if decision_filter:
            stmt = stmt.where(Opportunity.client_decision == decision_filter)

        result = await self.session.execute(stmt)
        rows = []
        for opp, sim in result.all():
            if sim >= threshold:
                rows.append((opp, float(sim)))
        return rows

    async def apply_feedback(
        self,
        opportunity_id: int,
        decision: str,
        reason: str | None,
        submitted_by: str | None = None,
    ) -> None:
        stmt = (
            update(Opportunity)
            .where(Opportunity.id == opportunity_id)
            .values(
                client_decision=decision,
                client_reason=reason,
                client_decided_at=datetime.utcnow(),
                status=decision,
            )
        )
        await self.session.execute(stmt)
        self.session.add(Feedback(
            opportunity_id=opportunity_id,
            decision=decision,
            reason=reason,
            submitted_by=submitted_by,
        ))


# ============================================================
# Run repo
# ============================================================

class RunRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def start_run(self) -> Run:
        run = Run()
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_run(self, run: Run, **fields) -> None:
        for k, v in fields.items():
            setattr(run, k, v)
        run.finished_at = datetime.utcnow()
        run.status = fields.get("status", "OK")


# ============================================================
# ScoringWeights repo
# ============================================================

class WeightsRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self) -> ScoringWeights | None:
        stmt = select(ScoringWeights).where(ScoringWeights.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_new_version(
        self,
        weights: dict[str, float],
        based_on_n_feedbacks: int,
        method: str = "logistic_regression",
    ) -> ScoringWeights:
        # Désactiver l'ancienne version active
        stmt_max = select(ScoringWeights).order_by(ScoringWeights.version.desc()).limit(1)
        last = (await self.session.execute(stmt_max)).scalar_one_or_none()
        new_version = (last.version + 1) if last else 1

        if last:
            await self.session.execute(
                update(ScoringWeights).where(ScoringWeights.is_active.is_(True)).values(is_active=False)
            )

        new_weights = ScoringWeights(
            version=new_version,
            weights=weights,
            based_on_n_feedbacks=based_on_n_feedbacks,
            method=method,
            is_active=True,
        )
        self.session.add(new_weights)
        await self.session.flush()
        return new_weights
