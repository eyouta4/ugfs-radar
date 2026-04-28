"""
src/analyzer/similarity.py — Comparaison sémantique avec les Go passés.

Ce module connecte le pipeline (analyzer LLM → scoring) à la base de
connaissances historique d'UGFS. Pour chaque nouvelle opportunité :

  1. On calcule l'embedding du texte canonique (titre + critères + géo)
  2. On cherche dans pgvector les K opportunités historiques marquées GO
     ou GO_SUBMITTED dont la cosine similarity dépasse un seuil
  3. On retourne (sim_max, titres_similaires) → injecté dans le scoring

Si la similarité est très élevée (≥ 0.85 par défaut), le scoring applique
un boost de +10 points, formalisant le principe « ce qui a marché doit
remarcher ».
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.analyzer.embeddings import VoyageEmbedder, opportunity_to_embedding_text
from src.config import AnalyzedOpportunity, RawOpportunity
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.storage.repository import OpportunityRepo

logger = get_logger(__name__)


@dataclass
class SimilarityResult:
    embedding: list[float]
    max_similarity: float
    similar_titles: list[str]
    raw_matches: list[tuple[str, float]]   # [(title, sim), ...] pour audit


async def find_similar_past_go(
    raw: RawOpportunity,
    analyzed: AnalyzedOpportunity,
    session: AsyncSession,
    embedder: VoyageEmbedder,
) -> SimilarityResult:
    """
    Cherche les opportunités historiques GO les plus proches.

    Args:
        raw: opportunité brute (pour l'URL/titre)
        analyzed: extraction LLM (pour le contenu sémantique)
        session: session DB async
        embedder: client Voyage

    Returns:
        SimilarityResult avec embedding, sim max, et titres similaires.
    """
    settings = get_settings()
    threshold = settings.similarity_boost_threshold

    # Construire le texte canonique
    text = opportunity_to_embedding_text(
        title=raw.title,
        summary=analyzed.summary_executive,
        eligibility=analyzed.eligibility_summary,
        geographies=analyzed.geographies,
        sectors=analyzed.sectors,
        partners=analyzed.partners_mentioned,
    )

    # Embed
    embedding = await embedder.embed_one(text, input_type="query")

    # Recherche pgvector — on remonte les top 5 et filtre
    repo = OpportunityRepo(session)
    matches = await repo.list_similar(
        embedding=embedding,
        threshold=0.0,                       # on récupère tout puis on filtre nous-mêmes
        limit=5,
        decision_filter="GO",
    )

    # `matches` = [(Opportunity, similarity), ...]
    above_threshold = [(opp.title, sim) for opp, sim in matches if sim >= threshold]
    max_sim = max((sim for _, sim in above_threshold), default=0.0)

    logger.info(
        "similarity_check",
        title=raw.title[:60],
        max_sim=round(max_sim, 3),
        n_above_threshold=len(above_threshold),
    )

    return SimilarityResult(
        embedding=embedding,
        max_similarity=max_sim,
        similar_titles=[t for t, _ in above_threshold],
        raw_matches=[(opp.title, sim) for opp, sim in matches],
    )
