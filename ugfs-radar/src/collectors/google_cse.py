"""
src/collectors/google_cse.py — Collecteur Google via SerpAPI (priorité) ou Google CSE.

Requêtes conçues à partir de l'historique réel UGFS :
- AOs soumis : TGF (GCF, Mitigation AF, Climate KIC, CIEIF, AEF, Adaptation Fund, APIA)
- Blue Bond : SIFI, APIA
- Seed of Change : AgriFI, Common Fund for Commodities
- NEW ERA : Fund Launch Partners (emerging fund manager)
- Sénégal FEVE : mandate cogestion fonds
"""
from __future__ import annotations

import asyncio

import httpx

from src.collectors.base import BaseCollector
from src.config.logger import get_logger
from src.config.schemas import RawOpportunity, SourceKind
from src.config.settings import get_settings

logger = get_logger(__name__)

# ── Requêtes principales ────────────────────────────────────────────────────
SERPAPI_QUERIES = [
    # === GCF / Fonds Vert — pilier TGF ===
    "green climate fund GCF Africa fund manager call proposals 2026",
    "fonds vert pour le climat FVC Afrique appel à propositions 2026",
    "GCF accredited entity fund manager Africa MENA 2026",
    "climate finance fund manager mandate Africa North 2026",

    # === Blended finance / emerging fund managers ===
    "emerging fund manager blended finance Africa call 2026",
    "call for fund managers Africa climate impact 2026",
    "blended finance fund manager mandate Africa MENA 2026",
    "convergence blended finance Africa call proposals 2026",

    # === Partenaires institutionnels clés ===
    "GIZ AFD appel à projets Afrique Tunisie fonds 2026",
    "AfDB African Development Bank fund manager mandate Africa 2026",
    "mitigation action facility call for projects Africa 2026",
    "adaptation fund call for proposals Africa 2026",
    "climate KIC call expression of interest fund Africa 2026",

    # === Blue economy / water ===
    "blue economy fund Mediterranean Africa call 2026",
    "SIFI SDG impact finance initiative water ocean Africa 2026",
    "water resilience fund Africa call proposals 2026",

    # === Agritech / food / SME ===
    "AgriFI Africa call for proposals SME agriculture 2026",
    "agritech food security grant Africa fund 2026",
    "common fund commodities Africa call proposals 2026",

    # === LinkedIn — source principale UGFS ===
    "site:linkedin.com call for proposals Africa fund manager climate 2026",
    "site:linkedin.com appel à projets fonds Afrique gestionnaire 2026",
    "site:linkedin.com emerging fund manager Africa blended finance 2026",
    "site:linkedin.com grant opportunity climate Africa MENA 2026",

    # === EU / Horizon Europe + Africa ===
    "Horizon Europe Africa Initiative call 2026 fund climate",
    "site:ec.europa.eu call for proposals Africa 2026 fund climate",
    "EU Africa co-fund climate blended finance 2026",

    # === Africa expansion + Europe synergie ===
    "IFC world bank Africa fund call proposals 2026 climate",
    "UNDP UNEP Africa call fund manager climate 2026",
    "KfW Proparco AFD Afrique appel gestionnaire fonds 2026",
]

# ── Requêtes bonus (si quota disponible) ────────────────────────────────────
BONUS_QUERIES = [
    "Finnpartnership call for proposals Africa 2026 fund",
    "CFYE challenge fund youth enterprise Africa 2026",
    "DRK Foundation Africa funding 2026 impact",
    "SDG Impact Finance SIFI call 2026 Africa water",
    "Renew Capital Africa fund 2026",
    "Africa50 fund manager call 2026",
    "Proparco appel fonds impact Afrique 2026",
    "FMO Netherlands Africa fund manager 2026",
    "appel à projets fonds climatique Afrique francophone 2026",
    "call for applications climate fund sub-saharan Africa 2026",
    "JIF joint innovation facility Africa Europe 2026",
    "APIA Tunisie appel à projets fonds vert 2026",
    "Africa EU cooperation fund climate finance 2026",
    "Kigali Amendment fund manager Africa 2026",
    "COP fund manager Africa climate 2026",
]


class GoogleCSECollector(BaseCollector):
    name = "google_cse"
    source_kind = SourceKind.GOOGLE_CSE.value

    def __init__(self, queries: list[str] | None = None, max_queries: int = 25):
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
        logger.warning("google_cse_not_configured",
                       hint="Set SERPAPI_KEY or GOOGLE_CSE_API_KEY+GOOGLE_CSE_ID")
        return []

    async def _collect_serpapi(self, api_key: str) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        seen_urls: set[str] = set()
        queries_to_run = self.queries[: self.max_queries]

        async with httpx.AsyncClient(timeout=25.0) as client:
            for query in queries_to_run:
                try:
                    r = await client.get(
                        "https://serpapi.com/search",
                        params={
                            "q": query,
                            "api_key": api_key,
                            "engine": "google",
                            "num": 10,
                            "gl": "tn",
                            "hl": "fr",
                        },
                    )
                    if r.status_code != 200:
                        logger.warning("serpapi_failed", status=r.status_code, query=query[:60])
                        continue

                    organic = r.json().get("organic_results", [])
                    n_added = 0
                    for item in organic:
                        title   = (item.get("title") or "").strip()
                        url     = (item.get("link") or "").strip()
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
                    await asyncio.sleep(0.6)

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
                            "num": 10,
                        },
                    )
                    if r.status_code != 200:
                        logger.warning("google_cse_query_failed",
                                       status=r.status_code, query=query[:60])
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
