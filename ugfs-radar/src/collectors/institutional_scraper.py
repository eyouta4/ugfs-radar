"""
src/collectors/institutional_scraper.py — Sources institutionnelles multiples.

Regroupe en un seul collecteur :
- World Bank Procurement (projects.worldbank.org)
- UNDP Procurement (procurement.undp.org)
- Devex Funding (devex.com)
- ReliefWeb Jobs & Opportunities (reliefweb.int)
- IFC / EIB via leurs APIs ouvertes

Ces sources sont toutes librement accessibles et très pertinentes pour UGFS.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import httpx

from src.config import RawOpportunity, SourceKind
from src.config.logger import get_logger

from .base import BaseCollector

logger = get_logger(__name__)

# Mots-clés pour pré-filtrage local (évite appels LLM inutiles)
RELEVANCE_KEYWORDS = [
    "fund", "fonds", "finance", "investment", "advisory", "mandate", "consultant",
    "climate", "green", "renewable", "environment", "water", "ocean", "blue",
    "agri", "food", "agriculture", "sme", "pme",
    "africa", "afrique", "mena", "north africa", "tunisia", "maghreb",
    "private equity", "blended", "impact", "grant", "subvention",
    "call for proposals", "rfp", "eoi", "expression of interest",
    "asset management", "fund manager",
]


def _is_relevant(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in RELEVANCE_KEYWORDS)


def _deadline_ok(deadline_str: str | None, min_days: int = 7) -> bool:
    """Retourne True si la deadline est dans le futur (≥ min_days)."""
    if not deadline_str:
        return True   # deadline inconnue → conserver, le LLM tranchera
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            dl = datetime.strptime(deadline_str[:10], fmt[:10]).date()
            return dl >= date.today() + timedelta(days=min_days)
        except ValueError:
            continue
    return True


class WorldBankScraper(BaseCollector):
    """Collecteur World Bank Procurement Notices."""
    name = "world_bank"
    source_kind = SourceKind.INSTITUTIONAL.value
    timeout = 30.0

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        # API World Bank Projects
        api_url = "https://search.worldbank.org/api/v2/projects"
        params = {
            "format": "json",
            "fl": "id,project_name,regionname,countryname,status,sector1,lendinginstrument,closingdate",
            "qterm": "fund manager advisory climate Africa",
            "rows": 20,
            "os": 0,
            "fct": "regionname_exact:Africa",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(api_url, params=params)
                if r.status_code != 200:
                    return []
                data = r.json()
                projects = data.get("projects", {})
                if isinstance(projects, dict):
                    items = list(projects.values())
                elif isinstance(projects, list):
                    items = projects
                else:
                    items = []

                for p in items[:15]:
                    title   = (p.get("project_name") or "").strip()
                    pid     = p.get("id") or ""
                    region  = p.get("regionname") or p.get("countryname") or "Africa"
                    sector  = p.get("sector1") or ""
                    closing = p.get("closingdate") or ""
                    if not title:
                        continue
                    if not _deadline_ok(closing[:10] if closing else None):
                        continue
                    combined = (title + " " + str(sector)).lower()
                    if not _is_relevant(combined):
                        continue

                    url = f"https://projects.worldbank.org/en/projects-operations/project-detail/{pid}"
                    raw_text = (
                        f"World Bank Project: {title}\n"
                        f"Region: {region}\nSector: {sector}\n"
                        f"Closing: {closing}"
                    )
                    results.append(RawOpportunity(
                        title=title[:500],
                        url=url,
                        source=self.name,
                        source_kind=SourceKind.INSTITUTIONAL,
                        raw_text=raw_text,
                        deadline_hint=closing[:10] if closing else None,
                    ))
        except Exception as exc:
            logger.warning("worldbank_error", error=str(exc))

        logger.info("worldbank_done", count=len(results))
        return results


class UNDPScraper(BaseCollector):
    """Collecteur UNDP Procurement Notices."""
    name = "undp"
    source_kind = SourceKind.INSTITUTIONAL.value
    timeout = 30.0

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        # UNDP Procurement Notices API
        api_url = "https://procurement-notices.undp.org/view_procurement_notice.cfm"
        # Fallback: utiliser l'API JSON si disponible
        json_url = "https://procurement.undp.org/api/notices"
        params = {
            "search": "climate finance fund advisory Africa",
            "limit": 20,
            "offset": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(json_url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    notices = data.get("notices", data.get("items", data.get("data", [])))
                    for n in (notices or [])[:15]:
                        title    = (n.get("title") or n.get("name") or "").strip()
                        nid      = n.get("id") or n.get("noticeId") or ""
                        country  = n.get("country") or n.get("location") or ""
                        deadline = n.get("deadline") or n.get("closingDate") or ""
                        if not title:
                            continue
                        if not _deadline_ok(str(deadline)[:10] if deadline else None):
                            continue
                        if not _is_relevant(title):
                            continue

                        url = f"https://procurement.undp.org/notice/{nid}" if nid else json_url
                        raw_text = (
                            f"UNDP Procurement: {title}\n"
                            f"Country: {country}\nDeadline: {deadline}"
                        )
                        results.append(RawOpportunity(
                            title=title[:500],
                            url=url,
                            source=self.name,
                            source_kind=SourceKind.INSTITUTIONAL,
                            raw_text=raw_text,
                            deadline_hint=str(deadline)[:10] if deadline else None,
                        ))
        except Exception as exc:
            logger.warning("undp_error", error=str(exc))

        logger.info("undp_done", count=len(results))
        return results


class DevexScraper(BaseCollector):
    """
    Collecteur Devex — via RSS + SerpAPI.
    Devex est une source majeure pour les AOs de développement international.
    """
    name = "devex"
    source_kind = SourceKind.AGGREGATOR.value
    timeout = 20.0

    DEVEX_QUERIES = [
        "site:devex.com fund manager Africa climate 2026",
        "site:devex.com advisory mandate Africa finance 2026",
        "site:devex.com call for proposals Africa investment 2026",
        "site:devex.com blended finance Africa grant 2026",
    ]

    async def collect(self) -> list[RawOpportunity]:
        from src.config.settings import get_settings
        settings = get_settings()
        results: list[RawOpportunity] = []

        serpapi_key = getattr(settings, "serpapi_key", None) or ""
        if not serpapi_key:
            logger.warning("devex_no_serpapi_key")
            return results

        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in self.DEVEX_QUERIES:
                try:
                    r = await client.get(
                        "https://serpapi.com/search",
                        params={
                            "q": query,
                            "api_key": serpapi_key,
                            "engine": "google",
                            "num": 8,
                        },
                    )
                    if r.status_code != 200:
                        continue
                    for item in r.json().get("organic_results", []):
                        title   = (item.get("title") or "").strip()
                        url     = (item.get("link") or "").strip()
                        snippet = (item.get("snippet") or "").strip()
                        if not (title and url and "devex.com" in url):
                            continue
                        if not _is_relevant(title + " " + snippet):
                            continue
                        results.append(RawOpportunity(
                            title=title,
                            url=url,
                            source=self.name,
                            source_kind=SourceKind.AGGREGATOR,
                            raw_text=f"{title}\n{snippet}",
                        ))
                    await asyncio.sleep(0.5)
                except Exception as exc:
                    logger.warning("devex_query_error", error=str(exc))

        logger.info("devex_done", count=len(results))
        return results


class ReliefWebScraper(BaseCollector):
    """
    Collecteur ReliefWeb — API publique, riche en AOs humanitaires/développement.
    https://reliefweb.int/help/api
    """
    name = "reliefweb"
    source_kind = SourceKind.AGGREGATOR.value
    timeout = 20.0

    RELIEFWEB_API = "https://api.reliefweb.int/v1/jobs"

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        params = {
            "appname": "ugfs-radar",
            "query[value]": "fund advisory climate Africa finance",
            "query[operator]": "AND",
            "filter[field]": "status",
            "filter[value]": "ongoing",
            "limit": 25,
            "fields[include][]": ["title", "url", "date", "body", "country", "theme"],
            "sort[]": "date:desc",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(self.RELIEFWEB_API, params=params)
                if r.status_code != 200:
                    return []
                data = r.json()
                for item in (data.get("data") or [])[:20]:
                    fields = item.get("fields") or {}
                    title  = (fields.get("title") or "").strip()
                    url    = fields.get("url") or f"https://reliefweb.int/job/{item.get('id')}"
                    body   = (fields.get("body") or "")[:800]
                    country_list = fields.get("country") or []
                    countries = ", ".join(
                        c.get("name", "") for c in country_list if isinstance(c, dict)
                    )
                    if not title:
                        continue
                    if not _is_relevant(title + " " + body):
                        continue

                    raw_text = f"{title}\nCountries: {countries}\n{body}"
                    results.append(RawOpportunity(
                        title=title[:500],
                        url=url,
                        source=self.name,
                        source_kind=SourceKind.AGGREGATOR,
                        raw_text=raw_text,
                    ))
        except Exception as exc:
            logger.warning("reliefweb_error", error=str(exc))

        logger.info("reliefweb_done", count=len(results))
        return results
