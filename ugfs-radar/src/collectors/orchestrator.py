"""
src/collectors/orchestrator.py — Orchestre tous les collecteurs en parallèle.

Sources actives (9 collecteurs) :
  1. GoogleCSECollector      — SerpAPI + Google CSE (29 requêtes ciblées UGFS)
  2. EUFundingCollector      — EU Funding & Tenders Portal (Horizon Europe Africa)
  3. RSSFeedsCollector       — AfDB, Adaptation Fund, CIF, AFD, Devex, Mitigation AF
  4. LinkedInPublicCollector — Posts LinkedIn publics via SerpAPI
  5. TEDScraper              — TED Europa (marchés publics UE)
  6. AfDBScraper             — Banque Africaine de Développement
  7. WorldBankScraper        — World Bank Procurement
  8. UNDPScraper             — UNDP Procurement Notices
  9. ReliefWebScraper        — ReliefWeb (développement international)
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
from .ted_scraper import TEDScraper
from .afdb_scraper import AfDBScraper
from .institutional_scraper import (
    WorldBankScraper,
    UNDPScraper,
    DevexScraper,
    ReliefWebScraper,
)

logger = get_logger(__name__)


def default_collectors() -> list[BaseCollector]:
    """La liste complète des collecteurs activés en production."""
    return [
        # Priorité haute — sources avec historique GO UGFS
        GoogleCSECollector(),       # SerpAPI : 29 requêtes ciblées
        EUFundingCollector(),       # EU Portal : Horizon Europe Africa
        RSSFeedsCollector(),        # RSS institutionnels
        LinkedInPublicCollector(),  # LinkedIn posts publics

        # Sources institutionnelles directes
        TEDScraper(),               # TED Europa
        AfDBScraper(),              # Banque Africaine de Développement
        WorldBankScraper(),         # World Bank
        UNDPScraper(),              # UNDP
        ReliefWebScraper(),         # ReliefWeb
        DevexScraper(),             # Devex (via SerpAPI)
    ]


async def run_all(collectors: Iterable[BaseCollector] | None = None) -> list[RawOpportunity]:
    """
    Lance tous les collecteurs en parallèle.
    Une exception dans un collecteur n'arrête pas les autres.
    """
    cols = list(collectors) if collectors is not None else default_collectors()
    logger.info("orchestrator_start", n_collectors=len(cols),
                names=[c.name for c in cols])

    results = await asyncio.gather(*[c.safe_collect() for c in cols])
    flat = [opp for sublist in results for opp in sublist]

    # Stats par source
    stats = {c.name: len(r) for c, r in zip(cols, results)}
    logger.info("orchestrator_done", total=len(flat), per_source=stats)
    return flat
