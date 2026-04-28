"""
src/collectors/base.py — Classe de base pour tous les collecteurs.

Fournit :
- HTTP client async configuré (httpx + http2)
- User-Agent rotation
- Rate limiting (semaphore + jitter)
- Retry exponential backoff (tenacity)
- Logging structuré
- Pattern uniforme `async def collect() -> list[RawOpportunity]`
"""
from __future__ import annotations

import abc
import asyncio
import random
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fake_useragent import UserAgent
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from src.config import RawOpportunity
from src.config.logger import get_logger

logger = get_logger(__name__)

_ua_pool = UserAgent(browsers=["chrome", "edge", "firefox"], os=["macos", "windows"])


class BaseCollector(abc.ABC):
    """Base pour tout scraper. Override `collect()`."""

    name: str = "base"
    source_kind: str = "institutional"
    timeout: float = 30.0
    max_concurrency: int = 5
    rate_limit_min: float = 1.0
    rate_limit_max: float = 3.0

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    @asynccontextmanager
    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """HTTP client async avec headers réalistes."""
        headers = {
            "User-Agent": _ua_pool.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
            follow_redirects=True,
            http2=True,
        ) as client:
            yield client

    async def fetch(self, client: httpx.AsyncClient, url: str) -> str:
        """Fetch une URL avec retry. Retourne le HTML/JSON brut."""
        async with self._semaphore:
            await asyncio.sleep(random.uniform(self.rate_limit_min, self.rate_limit_max))
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=2, min=2, max=20),
                retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
                reraise=True,
            ):
                with attempt:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.text
            return ""  # unreachable mais nécessaire pour le type checker

    @abc.abstractmethod
    async def collect(self) -> list[RawOpportunity]:
        """Retourne la liste des opportunités brutes trouvées."""
        ...

    async def safe_collect(self) -> list[RawOpportunity]:
        """Wrapper qui catch les exceptions pour ne pas crash le pipeline complet."""
        try:
            logger.info("collector_start", name=self.name)
            opps = await self.collect()
            logger.info("collector_done", name=self.name, count=len(opps))
            return opps
        except Exception as exc:
            logger.exception("collector_failed", name=self.name, error=str(exc))
            return []
