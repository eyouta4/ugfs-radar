"""src/analyzer — Couche d'enrichissement intelligent.

Pipeline standard pour une opportunité brute :
    raw  ─►  llm_analyzer.analyze()  ─►  similarity.find_similar_past_go()
         ─►  scoring.compute_score()  ─►  ScoredOpportunity (prête à stocker)
"""
from src.analyzer.embeddings import VoyageEmbedder, opportunity_to_embedding_text
from src.analyzer.scoring import compute_score
from src.analyzer.similarity import find_similar_past_go, SimilarityResult

# llm_analyzer importe `groq` qui n'est pas requis pour les tests de scoring
# pur (tests unitaires). On l'importe en lazy / try-except pour éviter de
# forcer cette dépendance dans tous les contextes.
try:
    from src.analyzer.llm_analyzer import LLMAnalyzer  # noqa: F401
except Exception:
    LLMAnalyzer = None  # type: ignore[assignment,misc]

__all__ = [
    "LLMAnalyzer",
    "VoyageEmbedder",
    "opportunity_to_embedding_text",
    "compute_score",
    "find_similar_past_go",
    "SimilarityResult",
]
