"""
src/collectors/google_cse.py — Collecteur via SerpAPI (remplace Google CSE).
100 recherches gratuites/mois. Zero configuration Google Cloud requise.
"""
from __future__ import annotations
import httpx
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.config.schemas import RawOpportunity, SourceKind
from src.collectors.base import BaseCollector

logger = get_logger(__name__)

DEFAULT_QUERIES = [
    "call for proposals 2026 climate fund Africa asset manager",
    "green climate fund Africa application 2026",
    "blended finance Africa call 2026",
    "adaptation fund Africa call for proposals",
    "AfDB call for proposals fund manager 2026",
    "GIZ call for proposals Africa 2026",
    "blue economy fund Mediterranean Africa 2026",
    "agritech grant Africa SME 2026",
    "emerging fund manager Africa investment 2026",
    "Horizon Europe call Africa 2026",
    "AFD appel projets Afrique 2026",
    "EU Africa fund manager mandate 2026",
    "climate resilience grant Africa 2026",
    "Tunisia investment fund opportunity 2026",
    "site:linkedin.com call for proposals Africa fund 2026",
    "site:linkedin.com grant opportunity climate Africa",
    "site:linkedin.com emerging fund manager Africa",
    "site:linkedin.com blended finance Africa 2026",
]

class GoogleCSECollector(BaseCollector):
    name = "google_cse"
    source_kind = SourceKind.GOOGLE_CSE.value

    def __init__(self, queries=None):
        super().__init__()
        self.queries = list(queries) if queries else DEFAULT_QUERIES

    async def collect(self) -> list[RawOpportunity]:
        settings = get_settings()
        
        # Essaie SerpAPI d'abord
        serpapi_key = getattr(settings, 'serpapi_key', None) or ''
        if serpapi_key:
            return await self._collect_serpapi(serpapi_key)
        
        # Fallback : Google CSE classique
        if not settings.google_cse_api_key or not settings.google_cse_id:
            logger.warning("google_cse_not_configured")
            return []
        return await self._collect_google_cse(settings)

    async def _collect_serpapi(self, api_key: str) -> list[RawOpportunity]:
        results = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for query in self.queries[:10]:  # Max 10 queries (quota)
                try:
                    r = await client.get(
                        "https://serpapi.com/search",
                        params={
                            "q": query,
                            "api_key": api_key,
                            "engine": "google",
                            "num": 5,
                            "gl": "us",
                            "hl": "en",
                        }
                    )
                    if r.status_code != 200:
                        logger.warning("serpapi_failed", status=r.status_code, query=query[:50])
                        continue
                    
                    data = r.json()
                    organic = data.get("organic_results", [])
                    for item in organic:
                        title = item.get("title", "")
                        url = item.get("link", "")
                        snippet = item.get("snippet", "")
                        if not title or not url:
                            continue
                        results.append(RawOpportunity(
                            title=title,
                            url=url,
                            source=self.name,
                            source_kind=SourceKind.GOOGLE_CSE,
                            raw_text=f"{title}\n{snippet}",
                        ))
                    logger.info("serpapi_query_ok", query=query[:50], n=len(organic))
                except Exception as e:
                    logger.warning("serpapi_error", error=str(e), query=query[:50])
        
        logger.info("collector_done", name=self.name, count=len(results))
        return results

    async def _collect_google_cse(self, settings) -> list[RawOpportunity]:
        results = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for query in self.queries:
                try:
                    r = await client.get(
                        "https://www.googleapis.com/customsearch/v1",
                        params={
                            "key": settings.google_cse_api_key,
                            "cx": settings.google_cse_id,
                            "q": query,
                            "num": 5,
                        }
                    )
                    if r.status_code != 200:
                        logger.warning("google_cse_query_failed", error=str(r.status_code), query=query[:50])
                        continue
                    for item in r.json().get("items", []):
                        results.append(RawOpportunity(
                            title=item.get("title", ""),
                            url=item.get("link", ""),
                            source=self.name,
                            source_kind=SourceKind.GOOGLE_CSE,
                            raw_text=item.get("snippet", ""),
                        ))
                except Exception as e:
                    logger.warning("google_cse_error", error=str(e))
        return results
