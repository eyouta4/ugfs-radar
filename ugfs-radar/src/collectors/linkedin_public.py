"""
src/collectors/linkedin_public.py — Posts LinkedIn publics.

ATTENTION conformité légale et CGU LinkedIn :
- On ne scrape JAMAIS de contenu derrière login.
- On scrape uniquement les pages publiques `linkedin.com/posts/...`
  et les profils `/company/...` accessibles sans compte.
- LinkedIn utilise du JS lourd → on utilise Playwright en mode headless.
- Le free tier de Playwright sur Railway requiert d'augmenter la mémoire à 1Go
  (cf railway.toml). Si ça pose problème, fallback : on utilise Bing/Google
  pour trouver les posts indexés et on lit les snippets.

Approche fallback retenue ici (la plus robuste, zéro install Playwright) :
- On laisse Google CSE indexer les posts LinkedIn pertinents.
- On enrichit avec quelques comptes spécifiques via leur RSS si dispo.

Pour une montée en gamme, ajouter Playwright + un proxy résidentiel.
"""
from __future__ import annotations

from src.config import RawOpportunity, SourceKind
from src.config.logger import get_logger

from .base import BaseCollector
from .google_cse import GoogleCSECollector

logger = get_logger(__name__)


# Comptes LinkedIn observés dans l'historique UGFS (tous publics)
LINKEDIN_ACCOUNTS_TO_FOLLOW = [
    "global-grants-and-opportunities-for-africa-gga",
    "africagreenembassy",
    "funds-for-impact",
    "entrepreneurs-catalyst-hub",
    "blendedfinance-developmentfinance-sustainablefinance",
    "bridger-pennington-670035127",
]


class LinkedInPublicCollector(BaseCollector):
    """
    Stratégie via Google CSE restreint à site:linkedin.com/posts/.
    Avantage : robuste, conforme, pas de Playwright.
    """
    name = "linkedin_via_cse"
    source_kind = SourceKind.LINKEDIN.value

    async def collect(self) -> list[RawOpportunity]:
        # On délègue au CSE collector avec des queries spécifiques LinkedIn
        queries = [
            f'site:linkedin.com/posts {kw}'
            for kw in [
                'call for proposals Africa fund',
                'grant opportunity climate Africa',
                'emerging fund manager Africa',
                'blue economy funding',
                'Tunisia green fund',
                'agritech grant Africa 2026',
            ]
        ]
        # On re-utilise le moteur Google CSE
        cse = GoogleCSECollector(queries=queries, results_per_query=4)
        opps = await cse.collect()
        # On overwrite la source pour la traçabilité
        for opp in opps:
            opp.source = f"{self.name}::{opp.source}"
            opp.source_kind = SourceKind.LINKEDIN
        logger.info("linkedin_via_cse_done", count=len(opps))
        return opps
