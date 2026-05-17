"""
scripts/ingest_feedback.py — CLI standalone d'ingestion des décisions UGFS.

Alternative à l'endpoint POST /api/feedback/excel : ce script lit un
fichier Excel modifié en local et applique les décisions Go/No-Go en DB
sans passer par l'API. Utile pour :
  - tests d'intégration sans démarrer le service web
  - reprise manuelle si problème d'API

Usage :
    python -m scripts.ingest_feedback path/to/UGFS-Radar_2026-04-27.xlsx
    python -m scripts.ingest_feedback path/to/file.xlsx --by "alice@ugfs-na.com"
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from openpyxl import load_workbook

from src.config.logger import get_logger
# Index réels des colonnes dans l'Excel (depuis excel_builder.py)
from src.delivery.excel_builder import (
    COL_ID, COL_TITLE, COL_DECISION, COL_REASON,
)
from src.storage.database import init_db, session_scope
from src.storage.repository import OpportunityRepo

logger = get_logger(__name__)

VALID_DECISIONS = {"GO", "NO_GO", "BORDERLINE", "SUBMITTED"}

# L'onglet "Toutes opportunites" (sans accent, format actuel du builder)
# avec données depuis la ligne 5 (titre L2, en-tête L4, données L5+).
DATA_SHEET = "Toutes opportunites"
DATA_START_ROW = 5


async def ingest(path: Path, submitted_by: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)

    wb = load_workbook(path, data_only=True, read_only=True)
    # Compat : accepte avec ou sans accent (anciens fichiers)
    sheet_name = None
    for candidate in (DATA_SHEET, "Toutes opportunités", "Opportunites"):
        if candidate in wb.sheetnames:
            sheet_name = candidate
            break
    if sheet_name is None:
        raise ValueError(
            f"Onglet de données introuvable. Attendu: '{DATA_SHEET}'. "
            f"Onglets disponibles: {wb.sheetnames}"
        )
    ws = wb[sheet_name]

    n_processed, n_skipped, errors = 0, 0, []
    await init_db()

    async with session_scope() as session:
        repo = OpportunityRepo(session)
        for i, row in enumerate(
            ws.iter_rows(min_row=DATA_START_ROW, values_only=True),
            start=DATA_START_ROW,
        ):
            if not row or row[COL_ID] is None:
                continue
            # Skip les lignes de légende (ID non numérique)
            try:
                opp_id = int(row[COL_ID])
            except (ValueError, TypeError):
                continue
            decision_raw = row[COL_DECISION]
            if not decision_raw:
                n_skipped += 1
                continue
            decision = str(decision_raw).strip().upper()
            if decision not in VALID_DECISIONS:
                errors.append(f"Ligne {i}: décision invalide '{decision}' "
                              f"(attendu: GO/NO_GO/BORDERLINE/SUBMITTED)")
                continue
            try:
                reason = (
                    str(row[COL_REASON]).strip()
                    if row[COL_REASON] is not None else None
                )
                await repo.apply_feedback(
                    opportunity_id=opp_id,
                    decision=decision,
                    reason=reason,
                    submitted_by=submitted_by,
                )
                n_processed += 1
                title_preview = (str(row[COL_TITLE]) if row[COL_TITLE] else "?")[:50]
                logger.debug(
                    "feedback_applied",
                    id=opp_id, decision=decision, title=title_preview,
                )
            except Exception as e:
                errors.append(f"Ligne {i} (ID={opp_id}): {e}")

    logger.info("ingested", processed=n_processed, skipped=n_skipped, errors=len(errors))
    return {"processed": n_processed, "skipped": n_skipped, "errors": errors}


def main():
    p = argparse.ArgumentParser(description="Ingère les décisions Go/No-Go d'un Excel UGFS-Radar.")
    p.add_argument("path", type=Path, help="Chemin du fichier Excel modifié")
    p.add_argument("--by", default="cli", help="Auteur des décisions (pour audit trail)")
    args = p.parse_args()

    result = asyncio.run(ingest(args.path, args.by))
    print(f"\n✓ Ingestion terminée")
    print(f"  Décisions appliquées : {result['processed']}")
    print(f"  Lignes ignorées      : {result['skipped']}")
    if result["errors"]:
        print(f"  Erreurs              : {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
