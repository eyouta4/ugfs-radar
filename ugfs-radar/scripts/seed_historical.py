"""
scripts/seed_historical.py — Charge les AO historiques d'UGFS dans la base.

Lit data/historical_ao.csv (généré dans la phase précédente à partir du CSV
brut UGFS), normalise, embed chaque ligne via Voyage AI, et insère dans la
table `opportunities` avec :
  - source_kind = MANUAL
  - status = client_decision (GO_SUBMITTED, GO_LOST, NO_GO, UNKNOWN)
  - embedding rempli → utilisable par la recherche similarité

À exécuter UNE FOIS au déploiement initial. Idempotent (UPSERT par fingerprint).
"""
from __future__ import annotations

import asyncio
import csv
from datetime import date, datetime
from pathlib import Path

from src.analyzer.embeddings import VoyageEmbedder, opportunity_to_embedding_text
from src.config.logger import get_logger
from src.config.settings import PROJECT_ROOT
from src.storage.database import init_db, session_scope
from src.storage.models import Opportunity
from src.storage.repository import compute_fingerprint

logger = get_logger(__name__)

CSV_PATH = PROJECT_ROOT / "data" / "historical_ao.csv"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_list(s: str | None) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in s.split(";") if p.strip()]


async def main():
    if not CSV_PATH.exists():
        logger.error("csv_not_found", path=str(CSV_PATH))
        raise FileNotFoundError(CSV_PATH)

    await init_db()
    embedder = VoyageEmbedder()

    # Charger CSV
    rows: list[dict] = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    logger.info("csv_loaded", n=len(rows))

    # Préparer les textes pour embedding batch
    texts = [
        opportunity_to_embedding_text(
            title=r.get("title", ""),
            summary=r.get("summary", ""),
            eligibility=r.get("eligibility", ""),
            geographies=_parse_list(r.get("geographies")),
            sectors=_parse_list(r.get("sectors")),
            partners=_parse_list(r.get("partners_mentioned")),
        )
        for r in rows
    ]

    # Embed en batch (économise les requêtes API)
    logger.info("embedding_batch_start", n=len(texts))
    embeddings = await embedder.embed_batch(texts, input_type="document")
    await embedder.aclose()

    # Insertion
    n_new = 0
    n_updated = 0
    async with session_scope() as session:
        from sqlalchemy import select
        for row, emb in zip(rows, embeddings):
            title = row.get("title", "").strip()
            url = row.get("url", "").strip() or f"manual://{title[:40]}"
            decision = (row.get("decision") or "UNKNOWN").strip().upper()
            deadline = _parse_date(row.get("deadline"))
            fingerprint = compute_fingerprint(title, url, deadline)

            existing = (await session.execute(
                select(Opportunity).where(Opportunity.fingerprint == fingerprint)
            )).scalar_one_or_none()

            if existing:
                # Update minimal
                existing.embedding = emb
                existing.client_decision = decision if decision != "UNKNOWN" else existing.client_decision
                existing.client_reason = row.get("decision_reason") or existing.client_reason
                n_updated += 1
                continue

            opp = Opportunity(
                fingerprint=fingerprint,
                title=title or "Untitled historical AO",
                url=url,
                source="seed_historical",
                source_kind="manual",
                summary_executive=(row.get("summary") or "")[:600],
                opportunity_type=(row.get("type") or "unknown").lower(),
                theme=(row.get("theme") or "unknown").lower(),
                geographies=_parse_list(row.get("geographies")),
                sectors=_parse_list(row.get("sectors")),
                eligibility_summary=(row.get("eligibility") or "")[:400],
                deadline=deadline,
                deadline_text_raw=row.get("deadline_raw"),
                ticket_size_usd=int(row["ticket_usd"]) if row.get("ticket_usd", "").isdigit() else None,
                languages=_parse_list(row.get("languages")),
                why_interesting=(row.get("why_interesting") or "")[:400],
                preliminary_decision=decision if decision in {"GO", "NO_GO", "BORDERLINE"} else "PENDING",
                decision_rationale=(row.get("decision_reason") or "")[:300],
                partners_mentioned=_parse_list(row.get("partners_mentioned")),
                vehicle_match=row.get("vehicle_match") or None,
                submission_url=row.get("submission_url") or None,
                score=int(row["score"]) if row.get("score", "").isdigit() else 0,
                score_breakdown={"_seed": "historical"},
                similarity_to_past_go=0.0,
                similar_past_opportunities=[],
                status="HISTORICAL",
                is_urgent=False,
                client_decision=decision if decision != "UNKNOWN" else None,
                client_reason=row.get("decision_reason") or None,
                client_decided_at=_parse_date(row.get("decision_date")) or datetime(2024, 1, 1).date(),
                embedding=emb,
            )
            session.add(opp)
            n_new += 1

    logger.info("seed_done", new=n_new, updated=n_updated)
    print(f"✓ Seed terminé : {n_new} nouvelles, {n_updated} mises à jour.")


if __name__ == "__main__":
    asyncio.run(main())
