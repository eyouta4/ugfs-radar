"""
src/collectors/google_cse.py — Collecteur Google via SerpAPI (priorité) ou Google CSE.

SerpAPI : 100 recherches gratuites/mois — zéro config Google Cloud requise.
Fallback Google CSE classique si pas de clé SerpAPI.
"""
from __future__ import annotations

import asyncio

import httpx

from src.collectors.base import BaseCollector
from src.config.logger import get_logger
from src.config.schemas import RawOpportunity, SourceKind
from src.config.settings import get_settings

logger = get_logger(__name__)

# Requêtes principales (chargées dans la collecte via SerpAPI)
SERPAPI_QUERIES = [
    # === AOs institutionnels (sources fiables) ===
    "call for proposals 2026 climate fund Africa asset manager",
    "green climate fund GCF Africa fund manager application 2026",
    "blended finance Africa emerging fund manager 2026",
    "adaptation fund Africa call for proposals 2026",
    "AfDB African Development Bank fund manager mandate 2026",
    "GIZ AFD call for proposals Afrique Nord Tunisie 2026",
    # === Thématiques UGFS ===
    "blue economy fund Mediterranean Africa 2026",
    "agritech food security grant Africa SME 2026",
    "Horizon Europe Africa Initiative call 2026 fund",
    "Tunisia investment climate fund opportunity 2026",
    # === LinkedIn (posts publics d'opportunités) ===
    "site:linkedin.com/posts call for proposals Africa fund 2026",
    "site:linkedin.com/posts grant opportunity climate Africa MENA",
    "site:linkedin.com/posts emerging fund manager Africa financing",
    "site:linkedin.com/posts blended finance Africa North 2026",
    # === EU Portal ===
    "site:ec.europa.eu call for proposals Africa 2026 fund",
    # === Partenaires prioritaires ===
    "convergence blended finance call 2026 Africa",
    "IFC world bank Africa fund call proposals 2026",
    "CFYE challenge fund youth enterprise 2026",
]

# Requêtes bonus pour les sources secondaires (utilisées si quota restant)
BONUS_QUERIES = [
    "Finnpartnership call for proposals Africa 2026",
    "Common Fund for Commodities call Africa 2026",
    "DRK Foundation Africa funding 2026",
    "MADICA Africa VC fund proposals 2026",
    "Renew Capital Africa fund 2026 apply",
    "SDG Impact Finance SIFI call 2026 Africa",
]


class GoogleCSECollector(BaseCollector):
    name = "google_cse"
    source_kind = SourceKind.GOOGLE_CSE.value

    def __init__(self, queries: list[str] | None = None, max_queries: int = 18):
        super().__init__()
        self.queries = list(queries) if queries else SERPAPI_QUERIES
        self.max_queries = max_queries

    async def collect(self) -> list[RawOpportunity]:
        settings = get_settings()

        serpapi_key = getattr(settings, "serpapi_key", None) or ""
        if serpapi_key:
            return await self._collect_serpapi(serpapi_key)

        if settings.google_cse_api_key and settings.google_cse_id:
            return await self._collect_google_cse(settings)

        logger.warning("google_cse_not_configured", hint="Set SERPAPI_KEY or GOOGLE_CSE_API_KEY+GOOGLE_CSE_ID")
        return []

    async def _collect_serpapi(self, api_key: str) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        seen_urls: set[str] = set()
        queries_to_run = self.queries[: self.max_queries]

        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in queries_to_run:
                try:
                    r = await client.get(
                        "https://serpapi.com/search",
                        params={
                            "q": query,
                            "api_key": api_key,
                            "engine": "google",
                            "num": 8,
                            "gl": "tn",   # Tunisia locale → résultats plus pertinents MENA
                            "hl": "fr",
                        },
                    )
                    if r.status_code != 200:
                        logger.warning("serpapi_failed", status=r.status_code, query=query[:60])
                        continue

                    organic = r.json().get("organic_results", [])
                    n_added = 0
                    for item in organic:
                        title = (item.get("title") or "").strip()
                        url = (item.get("link") or "").strip()
                        snippet = (item.get("snippet") or "").strip()
                        if not title or not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append(RawOpportunity(
                            title=title,
                            url=url,
                            source=self.name,
                            source_kind=SourceKind.GOOGLE_CSE,
                            raw_text=f"{title}\n{snippet}",
                        ))
                        n_added += 1

                    logger.info("serpapi_query_ok", query=query[:60], n=n_added)
                    await asyncio.sleep(0.5)   # respecte les rate limits SerpAPI

                except Exception as e:
                    logger.warning("serpapi_error", error=str(e), query=query[:60])

        logger.info("collector_done", name=self.name, count=len(results))
        return results

    async def _collect_google_cse(self, settings) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(timeout=15.0) as client:
            for query in self.queries[: self.max_queries]:
                try:
                    r = await client.get(
                        "https://www.googleapis.com/customsearch/v1",
                        params={
                            "key": settings.google_cse_api_key,
                            "cx": settings.google_cse_id,
                            "q": query,
                            "num": 8,
                        },
                    )
                    if r.status_code != 200:
                        logger.warning("google_cse_query_failed", status=r.status_code, query=query[:60])
                        continue
                    for item in r.json().get("items", []):
                        url = item.get("link", "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append(RawOpportunity(
                            title=item.get("title", ""),
                            url=url,
                            source=self.name,
                            source_kind=SourceKind.GOOGLE_CSE,
                            raw_text=item.get("snippet", ""),
                        ))
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.warning("google_cse_error", error=str(e), query=query[:60])

        logger.info("collector_done_cse", count=len(results))
        return results
