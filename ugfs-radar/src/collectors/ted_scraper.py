"""
src/collectors/ted_scraper.py — TED (Tenders Electronic Daily), portail officiel UE.

TED expose une API REST publique. On filtre sur :
- CPV codes liés finance/conseil/environnement
- Pays Afrique du Nord + EU (pour synergies)
- Statut actif (pas encore clôturé)

URL API : https://ted.europa.eu/api/v2.0/notices/search
"""
from __future__ import annotations

import httpx

from src.config import RawOpportunity, SourceKind
from src.config.logger import get_logger

from .base import BaseCollector

logger = get_logger(__name__)

TED_API = "https://ted.europa.eu/api/v2.0/notices/search"

# CPV codes pertinents pour UGFS
# 66000000 = Services financiers et d'assurance
# 73000000 = Recherche et développement + conseil
# 90700000 = Services environnementaux
# 71600000 = Services d'essais, d'analyse et conseil technique
CPV_CODES = [
    "66000000", "66100000", "66110000",   # Finance / banking
    "73000000", "73200000", "73300000",   # R&D / conseil
    "90700000", "90710000", "90720000",   # Environnement
    "71600000", "71621000",               # Conseil technique
    "79400000", "79410000", "79411000",   # Conseil en gestion
]

# Requête FULL-TEXT TED pour appels d'offres pertinents UGFS
TED_QUERIES = [
    "climate fund Africa advisory",
    "green finance Africa consultant",
    "impact investing Africa mandate",
    "blended finance advisory Africa",
    "renewable energy fund Africa",
    "environmental advisory North Africa",
    "climate adaptation fund consultant",
    "asset management Africa mandate",
]


class TEDScraper(BaseCollector):
    name = "ted_europa"
    source_kind = SourceKind.INSTITUTIONAL.value
    timeout = 45.0

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for query in TED_QUERIES[:6]:
                try:
                    payload = {
                        "query": query,
                        "scope": "ALL",
                        "fields": [
                            "ND", "TI", "TD", "DD", "DT", "CY",
                            "PC", "IA", "RC", "AU", "AC",
                        ],
                        "pageSize": 10,
                        "pageNum": 1,
                        "reverseOrder": False,
                        "onlyLatestVersions": True,
                        "searchType": "CONTRACT_NOTICE",
                    }
                    r = await client.post(TED_API, json=payload, timeout=30)
                    if r.status_code != 200:
                        logger.warning("ted_api_failed", status=r.status_code, query=query)
                        continue

                    data = r.json()
                    notices = data.get("notices", []) or data.get("results", []) or []

                    for notice in notices:
                        nd = str(notice.get("ND") or notice.get("id") or "")
                        if not nd or nd in seen_ids:
                            continue
                        seen_ids.add(nd)

                        title = (notice.get("TI") or notice.get("title") or "").strip()
                        if not title:
                            continue

                        deadline = notice.get("DD") or notice.get("deadlineDate") or ""
                        country = notice.get("CY") or notice.get("country") or ""
                        authority = notice.get("AU") or notice.get("authority") or ""
                        doc_type = notice.get("TD") or notice.get("documentType") or ""

                        url = f"https://ted.europa.eu/en/notice/{nd}"
                        raw_text = (
                            f"{title}\n"
                            f"Organisme: {authority}\n"
                            f"Pays: {country}\n"
                            f"Type: {doc_type}\n"
                            f"Query match: {query}"
                        )

                        results.append(RawOpportunity(
                            title=title[:500],
                            url=url,
                            source=self.name,
                            source_kind=SourceKind.INSTITUTIONAL,
                            raw_text=raw_text,
                            deadline_hint=str(deadline) if deadline else None,
                        ))

                    logger.info("ted_query_ok", query=query[:50], n=len(notices))

                except Exception as exc:
                    logger.warning("ted_query_error", query=query, error=str(exc))

        logger.info("ted_done", count=len(results))
        return results
