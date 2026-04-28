"""
src/analyzer/embeddings.py — Génération d'embeddings (Voyage AI).

Pourquoi Voyage AI ?
--------------------
Modèle voyage-3-lite (512 dims) offre :
  - 200M tokens gratuits / mois (largement assez pour UGFS-Radar)
  - Multilingue solide (FR/EN/AR couverts)
  - Performance proche de OpenAI text-embedding-3-small
  - Latence ~150ms

Usage :
  - Embed le texte d'une opportunité (titre + résumé + critères clés)
  - Embed les opportunités historiques au seed
  - Recherche pgvector cosine_similarity entre nouvelles AOs et Go passés

Si VOYAGE_API_KEY absente, on retourne un vecteur nul de la bonne dimension
(le scoring continuera de fonctionner, juste sans le boost similarité).
"""
from __future__ import annotations

import asyncio
from typing import Sequence

import httpx

from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)

VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
EMBEDDING_DIM = 512


class EmbeddingError(Exception):
    pass


class VoyageEmbedder:
    """Client async pour Voyage AI Embeddings API."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.voyage_api_key
        self.model = model or s.voyage_model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def embed_one(self, text: str, input_type: str = "document") -> list[float]:
        """
        Embed un seul texte.
        input_type: "document" (à indexer) ou "query" (à rechercher).
        """
        if not self.api_key:
            logger.warning("voyage_api_key_missing — returning zero vector")
            return [0.0] * EMBEDDING_DIM

        return (await self.embed_batch([text], input_type=input_type))[0]

    async def embed_batch(
        self,
        texts: Sequence[str],
        input_type: str = "document",
        batch_size: int = 16,
    ) -> list[list[float]]:
        """
        Embed plusieurs textes par batch (Voyage limite 128/req, on prend une marge).
        """
        if not self.api_key:
            logger.warning("voyage_api_key_missing — returning zero vectors")
            return [[0.0] * EMBEDDING_DIM for _ in texts]

        if not texts:
            return []

        # Tronque les textes trop longs (Voyage limite 32000 tokens = ~120k chars)
        cleaned = [self._clean_text(t) for t in texts]

        client = await self._get_client()
        results: list[list[float]] = []

        for i in range(0, len(cleaned), batch_size):
            chunk = cleaned[i : i + batch_size]
            try:
                resp = await client.post(
                    VOYAGE_API_URL,
                    json={
                        "input": chunk,
                        "model": self.model,
                        "input_type": input_type,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                vectors = [item["embedding"] for item in data["data"]]
                results.extend(vectors)
                logger.debug("voyage_batch_ok", n=len(chunk), model=self.model)
            except httpx.HTTPStatusError as e:
                logger.error(
                    "voyage_http_error",
                    status=e.response.status_code,
                    body=e.response.text[:300],
                )
                # Fallback : zero vector pour ce batch (le pipeline continue)
                results.extend([[0.0] * EMBEDDING_DIM for _ in chunk])
            except Exception as e:
                logger.error("voyage_unexpected_error", error=str(e))
                results.extend([[0.0] * EMBEDDING_DIM for _ in chunk])

            # Rate limit cool-down
            if i + batch_size < len(cleaned):
                await asyncio.sleep(0.2)

        return results

    @staticmethod
    def _clean_text(text: str) -> str:
        """Nettoie + tronque à 8000 chars (largement sous la limite tokens)."""
        if not text:
            return " "
        cleaned = " ".join(text.split())
        return cleaned[:8000] if len(cleaned) > 8000 else cleaned


# ============================================================
# Helper : texte canonique pour embedding d'une opportunité
# ============================================================

def opportunity_to_embedding_text(
    title: str,
    summary: str = "",
    eligibility: str = "",
    geographies: list[str] | None = None,
    sectors: list[str] | None = None,
    partners: list[str] | None = None,
) -> str:
    """
    Construit un texte canonique pour embedder une opportunité.
    L'ordre et la structure sont importants : on met les signaux forts en
    premier (titre, géographies, secteurs) pour que la similarité reflète
    bien le profil métier de l'AO.
    """
    parts = [
        f"Title: {title}",
        f"Geographies: {', '.join(geographies or []) or 'unspecified'}",
        f"Sectors: {', '.join(sectors or []) or 'unspecified'}",
        f"Partners: {', '.join(partners or []) or 'unspecified'}",
        f"Summary: {summary}",
        f"Eligibility: {eligibility}",
    ]
    return " | ".join(p for p in parts if p)
