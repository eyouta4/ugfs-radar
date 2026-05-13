"""
src/collectors/afdb_scraper.py — Banque Africaine de Développement.

Sources :
1. API Procurement AFDB : https://www.afdb.org/api/procurement
2. Open Data API projets : https://projectsportal.afdb.org/dataportal/
3. RSS Fallback

La BAD est un partenaire prioritaire UGFS (historique : GO_SUBMITTED sur plusieurs AOs).
"""
from __future__ import annotations

import httpx

from src.config import RawOpportunity, SourceKind
from src.config.logger import get_logger

from .base import BaseCollector

logger = get_logger(__name__)

AFDB_PROCUREMENT_API = "https://www.afdb.org/en/documents-and-publications/feed"
AFDB_PROJECTS_API    = "https://projectsportal.afdb.org/dataportal/api/project/search"

# Mots-clés pour filtrer les résultats pertinents UGFS
AFDB_KEYWORDS = [
    "fund manager", "asset management", "advisory", "consultant",
    "climate", "renewable", "green", "blue economy", "water",
    "finance", "investment", "private sector", "blended",
    "north africa", "tunisia", "maghreb", "mena",
    "call for proposals", "request for proposals", "rfp",
    "expression of interest", "eoi",
]


class AfDBScraper(BaseCollector):
    name = "afdb"
    source_kind = SourceKind.INSTITUTIONAL.value
    timeout = 30.0

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []

        # Source 1 : API projets AfDB (données ouvertes)
        try:
            results += await self._collect_projects()
        except Exception as exc:
            logger.warning("afdb_projects_failed", error=str(exc))

        # Source 2 : Requêtes SerpAPI ciblées AfDB via le collecteur Google
        results += self._afdb_serpapi_hints()

        logger.info("afdb_done", count=len(results))
        return results

    async def _collect_projects(self) -> list[RawOpportunity]:
        """Collecte les projets AfDB récents avec composante conseil/fonds."""
        opps: list[RawOpportunity] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            params = {
                "searchString": "fund manager advisory climate",
                "pageSize": 20,
                "pageIndex": 0,
                "projectStatus": "OnGoing,Pipeline",
                "sector": "Finance,Energy,Environment",
            }
            try:
                r = await client.get(AFDB_PROJECTS_API, params=params)
                if r.status_code == 200:
                    data = r.json()
                    projects = data.get("projects", data.get("items", []))
                    for p in projects[:15]:
                        title = (p.get("projectTitle") or p.get("title") or "").strip()
                        pid   = p.get("projectId") or p.get("id") or ""
                        country = p.get("country") or p.get("countryName") or "Africa"
                        sector  = p.get("sector") or ""
                        status  = p.get("projectStatus") or ""
                        if not title:
                            continue

                        url = f"https://projectsportal.afdb.org/dataportal/VProject/show/{pid}"
                        raw_text = (
                            f"AfDB Project: {title}\n"
                            f"Country: {country}\n"
                            f"Sector: {sector}\n"
                            f"Status: {status}"
                        )
                        # Pré-filtre : ne garder que les projets avec signaux UGFS
                        combined = (title + " " + sector).lower()
                        if any(kw in combined for kw in AFDB_KEYWORDS):
                            opps.append(RawOpportunity(
                                title=title[:500],
                                url=url,
                                source=self.name,
                                source_kind=SourceKind.INSTITUTIONAL,
                                raw_text=raw_text,
                            ))
            except Exception as exc:
                logger.warning("afdb_projects_api_error", error=str(exc))

        return opps

    def _afdb_serpapi_hints(self) -> list[RawOpportunity]:
        """
        Retourne des RawOpportunity avec les bonnes requêtes SerpAPI pour AfDB.
        Ces requêtes seront captées par le GoogleCSECollector lors de sa prochaine exécution.
        Ici on retourne juste des signaux d'intention pour le log.
        """
        # Les vraies requêtes SerpAPI sont dans google_cse.py
        # Ce collecteur existe pour être extensible
        return []
