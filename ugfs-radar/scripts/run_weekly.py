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
from datetime import date, datetime, timedelta

from src.analyzer.llm_analyzer import (
    analyze_opportunity, pre_filter, keyword_prescore, reset_provider_cache,
)
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
from src.delivery.pdf_builder import build_pdfs_zip
from src.storage.database import init_db, session_scope
from src.storage.repository import OpportunityRepo, RunRepo, WeightsRepo

logger = get_logger(__name__)

MAX_OPPS_PER_RUN = 50          # plafond LLM : top 50 pré-scorés par mots-clés
MAX_CONCURRENT_LLM = 4         # respecte rate limit Claude (4 appels simultanés)
GROQ_RPM_DELAY = 2.5           # délai entre appels Groq (tier gratuit ≈ 30 RPM → 2s min)

# Domaines officiels (URL plus prioritaire en cas de dédup)
_OFFICIAL_DOMAINS_PRIORITY = (
    "apia.com.tn", "afdb.org", "accf.afdb.org", "afd.fr", "convergence.finance",
    "greenclimate.fund", "adaptation-fund.org", "climate-kic.org", "eit.europa.eu",
    "ec.europa.eu", "europa.eu", "ted.europa.eu", "ebrd.com", "ecepp.ebrd.com",
    "ifc.org", "worldbank.org", "undp.org", "kfw.de", "get-invest.eu",
    "aecfafrica.org", "universalenergyfacility.org", "mitigation-action.org",
)


def _title_signature(title: str) -> set[str]:
    """Bag-of-words normalisé pour comparaison rapide (sans LLM)."""
    import re, unicodedata
    if not title:
        return set()
    # Normalise accents et casse
    nfkd = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    # Garde uniquement mots de 4+ caractères (skip stop-words courts)
    words = re.findall(r"[a-z0-9]+", s)
    stop = {"the", "and", "for", "with", "from", "into", "this", "that", "have",
            "will", "are", "was", "were", "been", "their", "they", "them",
            "pour", "avec", "dans", "des", "les", "une", "que", "qui", "est",
            "sur", "par", "aux", "ont", "des", "elle", "ils", "ces", "cette",
            "fund", "grant", "call", "appel", "project", "programme"}
    return {w for w in words if len(w) >= 4 and w not in stop}


def _semantic_dedup(opps: list) -> list:
    """
    Fusionne les AOs avec titres très similaires (Jaccard ≥ 0.5).
    Garde la version dont l'URL provient de la source la plus officielle.
    """
    if len(opps) <= 1:
        return opps

    # Signatures pré-calculées
    sigs = [_title_signature(o.title) for o in opps]

    def is_official(url: str) -> int:
        """Retourne un score 0-100 selon officialité du domaine."""
        url_lower = (url or "").lower()
        for i, dom in enumerate(_OFFICIAL_DOMAINS_PRIORITY):
            if dom in url_lower:
                return 100 - i   # plus haut = plus prioritaire
        # PDF officiel toujours mieux qu'un article
        if url_lower.endswith(".pdf"):
            return 50
        return 0

    keep = [True] * len(opps)
    for i in range(len(opps)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(opps)):
            if not keep[j]:
                continue
            sig_i, sig_j = sigs[i], sigs[j]
            if not sig_i or not sig_j:
                continue
            # Containment-based similarity (plus tolérant que Jaccard) :
            # un AO est doublon de l'autre si ≥ 60% de ses mots-clés sont
            # contenus dans l'autre, ET au moins 3 mots-clés communs.
            inter = len(sig_i & sig_j)
            min_len = min(len(sig_i), len(sig_j))
            if min_len == 0:
                continue
            containment = inter / min_len
            if containment >= 0.6 and inter >= 3:
                # Doublon sémantique → garder le plus officiel
                score_i = is_official(opps[i].url)
                score_j = is_official(opps[j].url)
                if score_j > score_i:
                    keep[i] = False
                    logger.info(
                        "semantic_dup_dropped",
                        kept=opps[j].title[:50],
                        dropped=opps[i].title[:50],
                        jaccard=round(jacc, 2),
                    )
                    break
                else:
                    keep[j] = False
                    logger.info(
                        "semantic_dup_dropped",
                        kept=opps[i].title[:50],
                        dropped=opps[j].title[:50],
                        jaccard=round(jacc, 2),
                    )
    return [o for i, o in enumerate(opps) if keep[i]]


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

    # Reset le cache de providers LLM désactivés (au cas où on retry après échec)
    reset_provider_cache()

    # Init DB (s'assurer pgvector + tables présentes + migrations légères)
    await init_db()

    # 0a. Re-appliquer le pre_filter aux AOs récentes (corrige les faux positifs
    # générés AVANT les dernières règles de filtrage). Idempotent.
    async with session_scope() as session:
        opp_repo = OpportunityRepo(session)
        n_demoted = await opp_repo.reapply_filters_to_recent(
            pre_filter_fn=pre_filter, cutoff_days=60,
        )
        await session.commit()
        if n_demoted:
            logger.info("filters_reapplied", demoted_to_no_go=n_demoted)

    # 0b. Reset : supprimer les AOs non-HISTORICAL et non-décidées de plus de 21 jours
    # (on garde plus longtemps maintenant pour gérer la dédup inter-semaines)
    cutoff_dt = datetime.utcnow() - timedelta(days=21)
    async with session_scope() as session:
        from sqlalchemy import delete as sa_delete
        from src.storage.models import Opportunity as OppModel
        stmt_del = (
            sa_delete(OppModel)
            .where(OppModel.status != "HISTORICAL")
            .where(OppModel.client_decision.is_(None))
            .where(OppModel.discovered_at < cutoff_dt)
        )
        result_del = await session.execute(stmt_del)
        await session.commit()
        logger.info("weekly_cleanup_done", deleted=result_del.rowcount, cutoff=cutoff_dt.isoformat())

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
    from src.collectors.orchestrator import run_all
    raw_opps = await run_all(collectors)
    logger.info("collection_done", n_raw=len(raw_opps))

    # 4a. Dédup intra-run — titre + URL exacts
    seen_keys: set[tuple] = set()
    deduped = []
    for r in raw_opps:
        key = (r.title.lower().strip(), r.url.split("?")[0].rstrip("/").lower())
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(r)
    logger.info("intra_run_dedup_exact", n=len(deduped))

    # 4a-bis. Dédup intra-run — titres très similaires (même AO, sources différentes)
    # Ex: "Tunisia receives €35.8m EU funding" (LinkedIn) == "EU boosts clean energy in
    # Tunisia with €35.8 million grant" (EIB). On les fusionne en gardant la source la
    # plus officielle (= URL la plus courte d'un domaine institutionnel).
    deduped = _semantic_dedup(deduped)
    logger.info("intra_run_dedup_semantic", n=len(deduped))

    # 4b. Pré-dédup contre la DB (évite de ré-analyser les AOs déjà connus)
    async with session_scope() as session:
        opp_repo = OpportunityRepo(session)
        known_urls = await opp_repo.get_known_urls(cutoff_days=30)

    truly_new = [
        r for r in deduped
        if r.url.split("?")[0].rstrip("/").lower() not in known_urls
    ]
    logger.info(
        "db_prededup",
        truly_new=len(truly_new),
        already_known=len(deduped) - len(truly_new),
    )
    deduped = truly_new

    # Pré-filtrage : éliminer les NO-GO évidents sans appel LLM
    pre_filtered = [r for r in deduped if not pre_filter(r)]
    n_prefilt = len(deduped) - len(pre_filtered)
    logger.info("pre_filter_done", removed=n_prefilt, remaining=len(pre_filtered))

    # Tri par score mots-clés → prendre les 50 meilleurs pour le LLM
    pre_filtered.sort(key=lambda r: keyword_prescore(r), reverse=True)
    if len(pre_filtered) > MAX_OPPS_PER_RUN:
        logger.info("capped_to_max", from_=len(pre_filtered), to=MAX_OPPS_PER_RUN)
        pre_filtered = pre_filtered[:MAX_OPPS_PER_RUN]
    deduped = pre_filtered

    # 5. Analyse + scoring
    embedder = VoyageEmbedder()
    settings_llm = get_settings()

    # Stratégie : si Anthropic configuré ET dispose de crédit → parallèle (4 concurrent)
    # Sinon (Groq/Cerebras/Gemini fallback) → séquentiel pour respecter les TPM limits.
    # La détection "Anthropic vraiment dispo" se fait dynamiquement : on test 1 AO
    # d'abord, et si Anthropic répond OK → mode parallèle, sinon → séquentiel.
    has_anthropic = bool(settings_llm.anthropic_api_key)

    # Probe : 1 AO en preview pour détecter si Anthropic répond (et donc skip après si crédit=0)
    use_parallel = False
    if has_anthropic and deduped:
        from src.analyzer.llm_analyzer import _DISABLED_PROVIDERS, _is_provider_disabled
        # On lance d'abord 1 AO pour voir si Anthropic répond. Si oui → parallèle.
        # Si Anthropic échoue avec crédit=0, il sera désactivé dans le cache.
        logger.info("llm_probe_anthropic", title=deduped[0].title[:60])
        probe_sem = asyncio.Semaphore(1)
        probe_result = await _process_one(deduped[0], embedder, weights, probe_sem)
        results = [probe_result]
        deduped_remaining = deduped[1:]
        # Si Anthropic n'est pas désactivé après ce 1er appel → on peut paralléliser
        use_parallel = not _is_provider_disabled("anthropic")
    else:
        results = []
        deduped_remaining = deduped

    if use_parallel and deduped_remaining:
        logger.info("llm_mode_parallel_anthropic", n=len(deduped_remaining))
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        tasks = [
            _process_one(raw, embedder, weights, semaphore)
            for raw in deduped_remaining
        ]
        more = await asyncio.gather(*tasks, return_exceptions=False)
        results.extend(more)
    elif deduped_remaining:
        logger.info(
            "llm_mode_sequential_fallback",
            n=len(deduped_remaining),
            delay_s=GROQ_RPM_DELAY,
        )
        sem1 = asyncio.Semaphore(1)
        for i, raw in enumerate(deduped_remaining):
            await asyncio.sleep(GROQ_RPM_DELAY)
            result = await _process_one(raw, embedder, weights, sem1)
            results.append(result)
            if (i + 1) % 5 == 0:
                logger.info("sequential_progress", done=i + 1, total=len(deduped_remaining))

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

    logger.info("scoring_done", new=n_new, updated=n_updated)

    # 7. Récupération pour delivery — AVEC DÉDUP INTER-SEMAINES
    # On récupère uniquement les AOs nouvelles ou ré-émergées depuis le dernier email,
    # plus celles déjà envoyées MAIS urgentes (deadline ≤ 14j) à rappeler.
    run_start_dt = datetime.utcnow()
    async with session_scope() as session:
        opp_repo = OpportunityRepo(session)
        new_opps, still_relevant = await opp_repo.list_for_weekly_email(
            run_started_at=run_start_dt,
            min_score=35,
        )
        recent = list(new_opps) + list(still_relevant)
        logger.info(
            "weekly_selection",
            new=len(new_opps),
            still_relevant=len(still_relevant),
            total=len(recent),
        )
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

        # 8b. Build PDFs ZIP
        try:
            zip_bytes, pdf_names = build_pdfs_zip(list(recent), run_date=today)
            logger.info("pdfs_zip_built", n_pdfs=len(pdf_names))
        except Exception as exc:
            logger.warning("pdfs_zip_failed", error=str(exc))
            zip_bytes = None

        # 9. Email (Excel + ZIP en pièces jointes)
        email_result = await send_weekly_email(
            list(recent), excel_bytes, run_date=today, zip_bytes=zip_bytes
        )

        # 9b. Marquer les AOs envoyées comme "déjà emailées" pour la dédup inter-semaines
        email_ok_for_mark = bool(email_result and not email_result.get("skipped"))
        if email_ok_for_mark and recent:
            opp_ids = [o.id for o in recent if hasattr(o, "id")]
            await opp_repo.mark_emailed(opp_ids)
            logger.info("opps_marked_emailed", n=len(opp_ids))

        # 10. Teams alerts
        teams_results = await send_urgent_alerts(list(urgent))

        # 11. Clôture run
        run_repo = RunRepo(session)
        from src.storage.models import Run
        run_obj = (await session.execute(
            select(Run).where(Run.id == run_id)
        )).scalar_one()
        email_ok = bool(email_result and not email_result.get("skipped"))
        await run_repo.finish_run(
            run_obj,
            status="OK",
            raw_collected=len(deduped),
            new_opportunities=n_new,
            urgent_alerts=len(urgent),
            notes=f"email={'sent' if email_ok else 'skipped'} | teams={len(teams_results)}",
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
