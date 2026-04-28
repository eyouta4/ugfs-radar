"""
scripts/run_weekly.py — Orchestration hebdomadaire complète.

PIPELINE
========
  1. Démarre un Run en DB (audit trail)
  2. Charge les poids de scoring actifs (fallback profil YAML)
  3. Collecte → tous les collecteurs en parallèle (asyncio.gather)
  4. Déduplique par fingerprint
  5. Pour chaque RawOpportunity (max N par exécution) :
        a. Analyzer LLM (Groq) → AnalyzedOpportunity
        b. Embedding (Voyage) → vecteur
        c. Recherche similarité avec Go passés
        d. Scoring → ScoredOpportunity
        e. Upsert DB + persist embedding
  6. Récupère toutes les opportunités récentes + l'historique
  7. Génère le fichier Excel hebdo
  8. Envoie l'email avec pièce jointe
  9. Envoie les alertes Teams pour les urgents
  10. Clôture le Run avec stats

Idempotent : ré-exécutable sans dégât (les fingerprints empêchent les doublons).
"""
from __future__ import annotations

import asyncio
import time
from datetime import date

from src.analyzer.llm_analyzer import analyze_opportunity
from src.analyzer import (
    VoyageEmbedder,
    compute_score,
    find_similar_past_go,
)
from src.analyzer.embeddings import opportunity_to_embedding_text
from src.collectors.orchestrator import default_collectors
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.delivery import (
    build_weekly_excel,
    send_urgent_alerts,
    send_weekly_email,
)
from src.storage.database import init_db, session_scope
from src.storage.repository import OpportunityRepo, RunRepo, WeightsRepo

logger = get_logger(__name__)

MAX_OPPS_PER_RUN = 80          # plafond pour limiter coûts LLM (~80 * 0 free Groq = 0€)
MAX_CONCURRENT_LLM = 4         # respecte rate limit Groq (30 RPM)


async def _process_one(
    raw,
    embedder: VoyageEmbedder,
    weights: dict,
    semaphore: asyncio.Semaphore,
):
    """Pipeline analyze → similarity → score → return ScoredOpportunity ou None."""
    async with semaphore:
        try:
            analyzed = await analyze_opportunity(raw)
            if analyzed is None:
                return None, None
        except Exception as e:
            logger.error("analyzer_failed", url=raw.url, error=str(e))
            return None, None

        # Similarity (a besoin d'une session DB → on la prend ici)
        async with session_scope() as session:
            try:
                sim = await find_similar_past_go(raw, analyzed, session, embedder)
            except Exception as e:
                logger.warning("similarity_failed", error=str(e))
                # Fallback : pas de similarité, juste l'embedding
                text = opportunity_to_embedding_text(
                    title=raw.title,
                    summary=analyzed.summary_executive,
                    eligibility=analyzed.eligibility_summary,
                    geographies=analyzed.geographies,
                    sectors=analyzed.sectors,
                    partners=analyzed.partners_mentioned,
                )
                emb = await embedder.embed_one(text)
                from src.analyzer.similarity import SimilarityResult
                sim = SimilarityResult(
                    embedding=emb, max_similarity=0.0,
                    similar_titles=[], raw_matches=[],
                )

        scored = compute_score(
            raw=raw,
            analyzed=analyzed,
            weights=weights,
            similarity_to_past_go=sim.max_similarity,
            similar_past_titles=sim.similar_titles,
        )
        return scored, sim.embedding


async def main() -> dict:
    started = time.monotonic()
    settings = get_settings()
    today = date.today()

    logger.info("weekly_run_started", date=today.isoformat(), env=settings.environment)

    # Init DB (s'assurer pgvector + tables présentes)
    await init_db()

    # 1. Démarrage du Run
    async with session_scope() as session:
        run_repo = RunRepo(session)
        weights_repo = WeightsRepo(session)
        run = await run_repo.start_run()
        run_id = run.id

        # 2. Charger les poids actifs
        active_weights_obj = await weights_repo.get_active()
        if active_weights_obj:
            weights = active_weights_obj.weights
            logger.info("active_weights_loaded", version=active_weights_obj.version)
        else:
            from src.config.settings import get_ugfs_profile
            weights = get_ugfs_profile().get("scoring_weights", {})
            logger.info("default_weights_loaded_from_yaml")

    # 3. Collecte
    collectors = default_collectors()
    collectors = default_collectors()
    from src.collectors.orchestrator import run_all
    raw_opps = await run_all(collectors)
    logger.info("collection_done", n_raw=len(raw_opps))

    # 4. Dédup intra-run
    seen = set()
    deduped = []
    for r in raw_opps:
        key = (r.title.lower().strip(), r.url.split("?")[0].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    logger.info("after_dedup", n=len(deduped))

    # Plafonnement
    if len(deduped) > MAX_OPPS_PER_RUN:
        logger.info("capped_to_max", from_=len(deduped), to=MAX_OPPS_PER_RUN)
        deduped = deduped[:MAX_OPPS_PER_RUN]

    # 5. Analyse + scoring en parallèle
    pass  # no class needed
    embedder = VoyageEmbedder()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)

    tasks = [
        _process_one(raw, analyzer, embedder, weights, semaphore)
        for raw in deduped
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # 6. Persistence
    n_new = 0
    n_updated = 0
    async with session_scope() as session:
        opp_repo = OpportunityRepo(session)
        for scored, embedding in results:
            if scored is None:
                continue
            existed = await opp_repo.exists(scored.fingerprint)
            opp = await opp_repo.upsert_scored(scored)
            if not existed and embedding is not None:
                await opp_repo.add_embedding(opp.id, embedding)
            if existed:
                n_updated += 1
            else:
                n_new += 1

    await embedder.aclose()
    pass

    logger.info("scoring_done", new=n_new, updated=n_updated)

    # 7. Récupération pour delivery
    async with session_scope() as session:
        opp_repo = OpportunityRepo(session)
        recent = await opp_repo.list_recent(days=7, only_open=True, min_score=0)
        urgent = await opp_repo.list_urgent_unprocessed()
        # Historique : les opportunités avec décision client (= corpus calibration)
        from sqlalchemy import select
        from src.storage.models import Opportunity
        stmt = (
            select(Opportunity)
            .where(Opportunity.client_decision.isnot(None))
            .order_by(Opportunity.client_decided_at.desc())
            .limit(200)
        )
        historical = (await session.execute(stmt)).scalars().all()

        # 8. Build Excel
        excel_bytes = build_weekly_excel(
            opportunities=list(recent),
            historical=list(historical),
            run_date=today,
        )

        # 9. Email
        email_result = await send_weekly_email(list(recent), excel_bytes, run_date=today)

        # 10. Teams alerts
        teams_results = await send_urgent_alerts(list(urgent))

        # 11. Clôture run
        run_repo = RunRepo(session)
        from src.storage.models import Run
        run_obj = (await session.execute(
            select(Run).where(Run.id == run_id)
        )).scalar_one()
        await run_repo.finish_run(
            run_obj,
            status="OK",
            n_collected=len(deduped),
            n_new=n_new,
            n_updated=n_updated,
            n_urgent=len(urgent),
            email_sent=bool(email_result and not email_result.get("skipped")),
            teams_alerts_sent=len(teams_results),
        )

    elapsed = round(time.monotonic() - started, 1)
    summary = {
        "run_id": run_id,
        "date": today.isoformat(),
        "elapsed_sec": elapsed,
        "collected": len(deduped),
        "new": n_new,
        "updated": n_updated,
        "urgent": len(urgent),
        "email_status": "sent" if email_result and not email_result.get("skipped") else "skipped",
        "teams_alerts": len(teams_results),
    }
    logger.info("weekly_run_done", **summary)
    return summary


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n=== UGFS-Radar weekly run ===")
    for k, v in result.items():
        print(f"  {k:>16} : {v}")
