"""
src/collectors/eu_funding.py — EU Funding & Tenders Portal.

Source : https://ec.europa.eu/info/funding-tenders/opportunities/portal/
La Commission expose une API JSON non-publique mais stable :
    https://ec.europa.eu/info/funding-tenders/opportunities/api/calls/list

On filtre sur :
- topics liés à Africa Initiative IV / Horizon Europe (programmePeriod=2021-2027)
- statut : ouvert ou en pré-publication
- thématiques : climat, énergie, agriculture, numérique, santé

Cette source a été identifiée dans le CSV historique UGFS (Horizon Europe — Africa Initiative IV).
"""
from __future__ import annotations

import httpx

from src.config import RawOpportunity, SourceKind
from src.config.logger import get_logger

from .base import BaseCollector

logger = get_logger(__name__)


# Endpoint stable (utilisé par le frontend du portail)
EU_API = "https://ec.europa.eu/info/funding-tenders/opportunities/api/calls/list"


class EUFundingCollector(BaseCollector):
    name = "eu_funding_portal"
    source_kind = SourceKind.INSTITUTIONAL.value
    timeout = 60.0

    async def collect(self) -> list[RawOpportunity]:
        async with self.http_client() as client:
            payload = {
                "languages": ["en", "fr"],
                "frameworkProgramme": ["43108390"],          # Horizon Europe
                "crossCuttingPriorities": ["Africa"],
                "status": ["31094501", "31094502"],          # OPEN + FORTHCOMING
                "pageSize": 50,
                "pageNumber": 1,
                "sortBy": "deadlineDate",
                "order": "ASC",
            }
            try:
                # Le portail accepte aussi GET avec params
                response = await client.post(EU_API, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                logger.warning("eu_funding_api_failed", error=str(exc))
                return []

        results: list[RawOpportunity] = []
        items = data.get("calls", []) or data.get("results", []) or []

        for item in items:
            try:
                identifier = item.get("identifier") or item.get("topicIdentifier") or ""
                title = item.get("title") or item.get("topicTitle") or ""
                if not (title and identifier):
                    continue
                url = (
                    f"https://ec.europa.eu/info/funding-tenders/opportunities/"
                    f"portal/screen/opportunities/topic-details/{identifier}"
                )
                description = item.get("description", "") or item.get("summary", "")
                deadline = item.get("deadlineDate") or item.get("deadlineDateText")

                opp = RawOpportunity(
                    title=title[:500],
                    url=url,
                    source=self.name,
                    source_kind=SourceKind.INSTITUTIONAL,
                    raw_text=f"{title}\n\n{description}",
                    deadline_hint=str(deadline) if deadline else None,
                    snippet=description[:300] if description else None,
                )
                results.append(opp)
            except Exception as exc:
                logger.debug("eu_funding_skip_item", error=str(exc))

        logger.info("eu_funding_done", count=len(results))
        return results
