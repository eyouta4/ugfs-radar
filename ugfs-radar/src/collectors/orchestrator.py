"""
src/collectors/orchestrator.py — Orchestre tous les collecteurs en parallèle.
"""
from __future__ import annotations

import asyncio
from typing import Iterable

from src.config import RawOpportunity
from src.config.logger import get_logger

from .base import BaseCollector
from .eu_funding import EUFundingCollector
from .google_cse import GoogleCSECollector
from .linkedin_public import LinkedInPublicCollector
from .rss_feeds import RSSFeedsCollector

logger = get_logger(__name__)


def default_collectors() -> list[BaseCollector]:
    """La liste par défaut des collecteurs activés."""
    return [
        GoogleCSECollector(),
        EUFundingCollector(),
        RSSFeedsCollector(),
        LinkedInPublicCollector(),
    ]


async def run_all(collectors: Iterable[BaseCollector] | None = None) -> list[RawOpportunity]:
    """
    Lance tous les collecteurs en parallèle.

    Une exception dans un collecteur n'arrête pas les autres
    (chaque collecteur retourne une liste vide en cas d'erreur via safe_collect).
    """
    cols = list(collectors) if collectors is not None else default_collectors()
    logger.info("orchestrator_start", n_collectors=len(cols),
                names=[c.name for c in cols])

    results = await asyncio.gather(*[c.safe_collect() for c in cols])
    flat = [opp for sublist in results for opp in sublist]

    # Stats par collecteur
    stats = {c.name: len(r) for c, r in zip(cols, results)}
    logger.info("orchestrator_done", total=len(flat), stats=stats)
    return flat
