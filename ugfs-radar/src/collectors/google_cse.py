"""
src/collectors/google_cse.py — Google Custom Search Engine.

Le moteur le plus puissant et le moins coûteux pour la recherche thématique large.
Free tier : 100 requêtes/jour. On lance ~10-15 requêtes par run hebdo, large marge.

Configuration côté Google :
1. https://programmablesearchengine.google.com → créer un moteur "tout le web"
2. Récupérer le `cx` (search engine ID)
3. https://console.cloud.google.com → activer "Custom Search API" → créer une API key
4. Coller les deux dans les variables d'env

Les queries sont calibrées sur le profil UGFS (cf data/ugfs_profile.yaml).
"""
from __future__ import annotations

from typing import Iterable

import httpx

from src.config import RawOpportunity, SourceKind, get_settings
from src.config.logger import get_logger

from .base import BaseCollector

logger = get_logger(__name__)

# Queries par défaut, basées sur le profil UGFS et l'historique observé.
# Chaque query est un trade-off entre précision (peu de bruit) et rappel (peu de manqués).
# Le nombre est volontairement limité (free tier = 100 req/jour, on lance 1×/semaine).
DEFAULT_QUERIES: list[str] = [
    # Green / climat - proche du Tunisia Green Fund
    'call for proposals 2026 climate Africa fund',
    'green climate fund Africa application 2026',
    'climate adaptation grant North Africa MENA',
    # Blue / eau / océan
    'blue economy fund Africa call for proposals',
    'water resilience grant North Africa 2026',
    # Asset management / GP
    'emerging fund manager Africa investment opportunity',
    'asset management mandate Africa MENA RFP',
    'private equity co-investment Africa Europe',
    # Agritech / Seed of Change
    'agritech grant Africa SME funding 2026',
    # Mandats / advisory
    'advisory mandate development finance Africa',
    'consultancy RFP impact investing Africa',
    # Synergie EU
    'Horizon Europe Africa Initiative call',
    # General development finance
    'AfDB IFC call for proposals 2026',
]


class GoogleCSECollector(BaseCollector):
    name = "google_cse"
    source_kind = SourceKind.GOOGLE_CSE.value
    rate_limit_min = 0.5
    rate_limit_max = 1.5

    def __init__(self, queries: Iterable[str] | None = None, results_per_query: int = 5):
        super().__init__()
        self.queries = list(queries) if queries else DEFAULT_QUERIES
        self.results_per_query = results_per_query
        self._endpoint = "https://www.googleapis.com/customsearch/v1"

    async def _search_one(self, client: httpx.AsyncClient, query: str) -> list[RawOpportunity]:
        settings = get_settings()
        if not (settings.google_cse_api_key and settings.google_cse_id):
            logger.warning("google_cse_not_configured")
            return []
        params = {
            "key": settings.google_cse_api_key,
            "cx": settings.google_cse_id,
            "q": query,
            "num": min(self.results_per_query, 10),
            "lr": "lang_fr|lang_en",
            "dateRestrict": "m6",   # opportunités publiées dans les 6 derniers mois
        }
        try:
            response = await client.get(self._endpoint, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("google_cse_query_failed", query=query, error=str(exc))
            return []

        items = data.get("items", [])
        opps: list[RawOpportunity] = []
        for item in items:
            try:
                opp = RawOpportunity(
                    title=item.get("title", "")[:500],
                    url=item.get("link", ""),
                    source=f"{self.name}::{query[:60]}",
                    source_kind=SourceKind.GOOGLE_CSE,
                    raw_text=item.get("snippet", "") + "\n\n" + item.get("title", ""),
                    snippet=item.get("snippet", ""),
                )
                opps.append(opp)
            except Exception as exc:
                logger.debug("google_cse_skip_item", error=str(exc), item=str(item)[:200])
        logger.info("google_cse_query_done", query=query, results=len(opps))
        return opps

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        async with self.http_client() as client:
            for query in self.queries:
                results.extend(await self._search_one(client, query))
        return results
