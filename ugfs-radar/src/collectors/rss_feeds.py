"""
src/collectors/rss_feeds.py — Collecteur RSS générique.

Beaucoup d'institutions exposent un flux RSS de leurs appels à projets :
- AfDB Procurement : https://www.afdb.org/en/projects-and-operations/procurement/feed
- Adaptation Fund : https://www.adaptation-fund.org/feed/
- Climate Investment Funds : https://www.cif.org/news/rss.xml
- IFC : https://disclosures.ifc.org/api/rss/projects
- AFD : https://www.afd.fr/fr/feed/news.xml

Ce collecteur les ingère tous d'un coup avec feedparser. C'est l'approche la
plus robuste : pas de scraping HTML fragile, juste du XML structuré.
"""
from __future__ import annotations

import feedparser

from src.config import RawOpportunity, SourceKind
from src.config.logger import get_logger

from .base import BaseCollector

logger = get_logger(__name__)


# (label, url, source_kind)
DEFAULT_FEEDS: list[tuple[str, str, SourceKind]] = [
    ("afdb", "https://www.afdb.org/en/news-and-events/feed", SourceKind.INSTITUTIONAL),
    ("adaptation_fund", "https://www.adaptation-fund.org/feed/", SourceKind.INSTITUTIONAL),
    ("cif", "https://www.cif.org/news/rss.xml", SourceKind.INSTITUTIONAL),
    ("afd_news", "https://www.afd.fr/fr/feed/news.xml", SourceKind.INSTITUTIONAL),
    ("climate_kic", "https://www.climate-kic.org/feed/", SourceKind.INSTITUTIONAL),
    # Nota : si une source bloque le user-agent par défaut feedparser, on peut
    # passer par self.fetch() puis feedparser.parse(content). Voir _parse_with_httpx.
]

# Mots-clés pour pré-filtrer (un AO doit contenir au moins l'un d'eux pour être retenu)
KEYWORDS = [
    "call for proposals", "call for projects", "appel à projets", "appel à propositions",
    "request for proposals", "rfp", "expression of interest", "manifestation d'intérêt",
    "grant", "subvention", "funding", "financement", "tender", "appel d'offres",
    "fund manager", "asset management", "advisory", "consultancy",
    "africa", "afrique", "mena", "north africa", "tunisia", "tunisie",
]


class RSSFeedsCollector(BaseCollector):
    name = "rss_feeds"
    source_kind = SourceKind.RSS.value
    rate_limit_min = 0.2
    rate_limit_max = 0.8

    def __init__(self, feeds: list[tuple[str, str, SourceKind]] | None = None):
        super().__init__()
        self.feeds = feeds or DEFAULT_FEEDS

    @staticmethod
    def _is_relevant(text: str) -> bool:
        lowered = text.lower()
        return any(kw in lowered for kw in KEYWORDS)

    async def _parse_with_httpx(self, url: str) -> list[dict]:
        """Pour les feeds qui rejettent le UA feedparser par défaut."""
        async with self.http_client() as client:
            try:
                content = await self.fetch(client, url)
                parsed = feedparser.parse(content)
                return parsed.entries
            except Exception as exc:
                logger.warning("rss_fetch_failed", url=url, error=str(exc))
                return []

    async def collect(self) -> list[RawOpportunity]:
        results: list[RawOpportunity] = []
        for label, url, kind in self.feeds:
            entries = await self._parse_with_httpx(url)
            for entry in entries:
                title = entry.get("title", "") or ""
                summary = entry.get("summary", "") or entry.get("description", "") or ""
                link = entry.get("link", "") or ""
                if not (title and link):
                    continue
                full_text = f"{title}\n\n{summary}"
                if not self._is_relevant(full_text):
                    continue

                try:
                    opp = RawOpportunity(
                        title=title[:500],
                        url=link,
                        source=f"{self.name}::{label}",
                        source_kind=kind,
                        raw_text=full_text,
                        snippet=summary[:300] if summary else None,
                        deadline_hint=entry.get("published") or entry.get("updated"),
                    )
                    results.append(opp)
                except Exception as exc:
                    logger.debug("rss_skip_entry", label=label, error=str(exc))
            logger.info("rss_feed_done", label=label, retained=sum(1 for r in results if label in r.source))
        return results
