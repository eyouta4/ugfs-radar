"""
scripts/seed_historical.py — Charge les AO historiques UGFS dans la base.

Lit data/historical_ao.csv (export du tableau de travail UGFS) et insère
chaque ligne avec :
  - source_kind = MANUAL
  - status = HISTORICAL
  - embedding rempli → utilisable par la recherche similarité
  - client_decision remplie depuis `inferred_decision`

Colonnes du CSV :
  opportunity_name, link, type, ugfs_eligible, is_open,
  deadline, actions_taken, final_response, inferred_decision, inferred_reason

Idempotent (UPSERT par fingerprint).
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

# Mapping inferred_decision → client_decision normalisé
DECISION_MAP = {
    "GO_SUBMITTED": "GO_SUBMITTED",
    "GO_LOST": "GO_LOST",
    "NO_GO": "NO_GO",
    "UNKNOWN": None,
    "": None,
}

# Inférence thème + véhicule depuis le champ "type" libre du CSV
VEHICLE_KEYWORDS = {
    "TGF": ["tgf", "tunisia green fund", "vert pour le climat", "gcf", "fvc", "climatique",
             "climate", "renewable", "solar", "énergie", "energy", "mitigation", "adaptation fund"],
    "BLUE_BOND": ["blue bond", "blue", "eau", "water", "ocean", "maritime", "sifi", "water resilience"],
    "SEED_OF_CHANGE": ["seed of change", "agritech", "agri", "agriculture", "food", "alimentaire",
                       "commodity", "sme", "pme"],
    "NEW_ERA": ["new era", "emerging fund", "venture", "digital", "numérique", "innovation",
                "startup", "tech"],
    "MUSANADA": ["musanada", "infrastructure", "social housing", "logement", "urban"],
}

THEME_KEYWORDS = {
    "green": ["climat", "climate", "green", "vert", "solar", "solaire", "renewable",
              "energy", "énergie", "mitigation", "adaptation", "co2"],
    "blue": ["blue", "eau", "water", "ocean", "maritime", "sifi", "océan"],
}


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    if s.lower() in ("rolling", "non précisé", "pas précisé", "à venir", "non lancé",
                     "lancement à venir", "appel à venir", "non lancé", ""):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _infer_theme(type_text: str) -> str:
    t = type_text.lower()
    for theme, kws in THEME_KEYWORDS.items():
        if any(k in t for k in kws):
            return theme
    return "generaliste"


def _infer_vehicle(type_text: str, name: str) -> str | None:
    combined = (type_text + " " + name).lower()
    for code, kws in VEHICLE_KEYWORDS.items():
        if any(k in combined for k in kws):
            return code
    return None


def _infer_type(type_text: str) -> str:
    t = type_text.lower()
    if any(k in t for k in ["grant", "subvention", "appel à projets", "call for proposal"]):
        return "grant"
    if any(k in t for k in ["advisory", "conseil", "rfp", "consultation"]):
        return "advisory"
    if any(k in t for k in ["mandat", "mandate", "cogestion", "fund manager"]):
        return "mandate"
    if any(k in t for k in ["fund", "fonds", "investment", "investissement"]):
        return "asset_management"
    return "unknown"


async def main():
    if not CSV_PATH.exists():
        logger.error("csv_not_found", path=str(CSV_PATH))
        raise FileNotFoundError(CSV_PATH)

    await init_db()
    embedder = VoyageEmbedder()

    rows: list[dict] = []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    logger.info("csv_loaded", n=len(rows))

    # Dédupliquer par (name, link) avant insertion
    seen: set[str] = set()
    unique_rows = []
    for row in rows:
        name = (row.get("opportunity_name") or "").strip()
        link = (row.get("link") or "").strip()
        key = f"{name.lower()[:100]}|{link.lower()[:100]}"
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)
    logger.info("after_dedup", n=len(unique_rows))

    # Préparer les textes pour embedding
    texts = []
    for r in unique_rows:
        name = (r.get("opportunity_name") or "").strip()
        type_text = (r.get("type") or "").strip()
        summary = f"{name}. {type_text}"
        texts.append(opportunity_to_embedding_text(
            title=name,
            summary=summary,
            eligibility=(r.get("ugfs_eligible") or ""),
            geographies=["Afrique", "MENA"],
            sectors=[],
            partners=[],
        ))

    logger.info("embedding_batch_start", n=len(texts))
    embeddings = await embedder.embed_batch(texts, input_type="document")
    await embedder.aclose()

    n_new = 0
    n_updated = 0
    n_skipped = 0

    async with session_scope() as session:
        from sqlalchemy import select

        for row, emb in zip(unique_rows, embeddings):
            name = (row.get("opportunity_name") or "").strip()
            if not name or len(name) < 3:
                n_skipped += 1
                continue

            link = (row.get("link") or "").strip()
            if not link.startswith("http"):
                link = f"manual://{name[:60].replace(' ', '_')}"

            deadline = _parse_date(row.get("deadline"))
            type_text = (row.get("type") or "").strip()
            raw_decision = (row.get("inferred_decision") or "").strip().upper()
            client_decision = DECISION_MAP.get(raw_decision, None)
            decision_reason = (row.get("inferred_reason") or "").strip()
            if decision_reason.startswith("[À CONFIRMER"):
                decision_reason = ""

            fingerprint = compute_fingerprint(name, link, deadline)

            existing = (await session.execute(
                select(Opportunity).where(Opportunity.fingerprint == fingerprint)
            )).scalar_one_or_none()

            if existing:
                existing.embedding = emb
                if client_decision and not existing.client_decision:
                    existing.client_decision = client_decision
                    existing.client_reason = decision_reason or existing.client_reason
                n_updated += 1
                continue

            # Inférences depuis le texte libre
            theme = _infer_theme(type_text)
            vehicle = _infer_vehicle(type_text, name)
            opp_type = _infer_type(type_text)

            # Décision préliminaire
            if client_decision in ("GO_SUBMITTED", "GO_LOST"):
                prelim = "GO"
            elif client_decision == "NO_GO":
                prelim = "NO_GO"
            else:
                prelim = "PENDING"

            opp = Opportunity(
                fingerprint=fingerprint,
                title=name,
                url=link,
                source="seed_historical",
                source_kind="manual",
                summary_executive=(f"{name}. {type_text}"[:600]),
                opportunity_type=opp_type,
                theme=theme,
                geographies=["Afrique", "MENA"],
                sectors=[],
                eligibility_summary=(row.get("ugfs_eligible") or "")[:400],
                deadline=deadline,
                deadline_text_raw=(row.get("deadline") or "").strip()[:200] or None,
                ticket_size_usd=None,
                languages=["fr", "en"],
                why_interesting=(type_text[:400] if type_text else "AO historique UGFS"),
                preliminary_decision=prelim,
                decision_rationale=(decision_reason[:300] if decision_reason else ""),
                partners_mentioned=[],
                vehicle_match=vehicle,
                submission_url=link if link.startswith("http") else None,
                score=80 if client_decision in ("GO_SUBMITTED",) else
                      60 if client_decision == "GO_LOST" else
                      10 if client_decision == "NO_GO" else 0,
                score_breakdown={"_seed": "historical", "_decision": raw_decision},
                similarity_to_past_go=0.0,
                similar_past_opportunities=[],
                status="HISTORICAL",
                is_urgent=False,
                client_decision=client_decision,
                client_reason=decision_reason or None,
                client_decided_at=datetime.utcnow(),
                embedding=emb,
            )
            session.add(opp)
            n_new += 1

    logger.info("seed_done", new=n_new, updated=n_updated, skipped=n_skipped)
    print(f"\n✓ Seed historique terminé :")
    print(f"  Nouvelles    : {n_new}")
    print(f"  Mises à jour : {n_updated}")
    print(f"  Ignorées     : {n_skipped}")


if __name__ == "__main__":
    asyncio.run(main())
