"""
src/config/schemas.py — Schémas Pydantic partagés entre les modules.

Ces classes définissent la forme exacte des données qui circulent dans le
pipeline : RawOpportunity (ce que produit un collecteur) → AnalyzedOpportunity
(ce que produit le LLM) → ScoredOpportunity (ce qui finit en DB et dans l'Excel).
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


# ============================================================
# Énumérations
# ============================================================

class Decision(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"
    BORDERLINE = "BORDERLINE"
    PENDING = "PENDING"


class OpportunityType(str, Enum):
    ASSET_MANAGEMENT = "asset_management"
    GRANT = "grant"
    ADVISORY = "advisory"
    MANDATE = "mandate"
    UNKNOWN = "unknown"


class Theme(str, Enum):
    GREEN = "green"
    BLUE = "blue"
    GENERAL = "generaliste"
    UNKNOWN = "unknown"


class SourceKind(str, Enum):
    """Type de source de scraping."""
    INSTITUTIONAL = "institutional"          # AfDB, IFC, EU Funding Portal
    LINKEDIN = "linkedin"
    GOOGLE_CSE = "google_cse"
    RSS = "rss"
    NEWSLETTER = "newsletter"
    MANUAL = "manual"                         # entrée manuelle UGFS


# ============================================================
# Schémas de pipeline
# ============================================================

class RawOpportunity(BaseModel):
    """
    Ce qu'un collecteur retourne. Brut, non-analysé, non-dédupliqué.
    Contient juste assez de signaux pour passer à l'étape Analyzer.
    """
    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=3, max_length=500)
    url: str = Field(..., max_length=2000)         # URL canonique de la page d'opportunité
    source: str                                     # nom du collecteur, ex "afdb_scraper"
    source_kind: SourceKind
    raw_text: str = Field(..., min_length=20)      # texte brut récupéré (sera passé au LLM)
    discovered_at: datetime = Field(default_factory=datetime.utcnow)

    # Champs optionnels pré-remplis si la source les donne
    deadline_hint: str | None = None              # texte brut de deadline (à parser plus tard)
    image_url: str | None = None
    snippet: str | None = None                    # résumé court fourni par la source

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(f"URL invalide: {v}")
        return v.strip()


class AnalyzedOpportunity(BaseModel):
    """
    Output structuré du LLM analyzer.
    Le prompt force le LLM à retourner un JSON exactement de cette forme.
    """
    model_config = ConfigDict(extra="ignore")

    # Identité
    title: str
    summary_executive: str = Field(..., max_length=600,
                                    description="Résumé exécutif en 3-4 phrases, en français")

    # Classification
    opportunity_type: OpportunityType
    theme: Theme
    geographies: list[str] = Field(default_factory=list,
                                   description="Liste des géographies/pays mentionnés")
    sectors: list[str] = Field(default_factory=list,
                               description="Secteurs spécifiques (énergie, agriculture, etc.)")

    # Critères clés
    eligibility_summary: str = Field(..., max_length=400,
                                     description="Qui peut postuler ? Conditions clés")
    deadline: date | None = Field(None, description="Deadline parsée. None si rolling/non précisée")
    deadline_text_raw: str | None = None          # ex "Rolling", "À venir", "fin Q1 2026"
    ticket_size_usd: int | None = None             # parsé depuis le texte si disponible
    languages: list[str] = Field(default_factory=list)

    # Recommandation préliminaire IA
    why_interesting: str = Field(..., max_length=400,
                                 description="2-3 raisons pour lesquelles c'est pertinent pour UGFS")
    preliminary_decision: Decision = Decision.PENDING
    decision_rationale: str = Field(..., max_length=300)

    # Mentions de partenaires connus
    partners_mentioned: list[str] = Field(default_factory=list)
    vehicle_match: str | None = Field(None, description="Code du véhicule UGFS qui matche, ou None")

    # Lien direct vers le formulaire de soumission si l'IA l'a trouvé
    submission_url: str | None = None

    # Raisonnement chain-of-thought (capturé pour auditabilité)
    analyst_reasoning: str | None = Field(
        None,
        max_length=2000,
        description="Raisonnement CoT en 3 étapes : admissibilité → alignement → décision",
    )


class ScoredOpportunity(BaseModel):
    """Opportunité finale, scorée et prête à être stockée + livrée."""
    model_config = ConfigDict(extra="ignore")

    # Hash unique (pour dédup)
    fingerprint: str

    # Toutes les données analysées
    raw: RawOpportunity
    analyzed: AnalyzedOpportunity

    # Score final
    score: int = Field(..., ge=0, le=100)
    score_breakdown: dict[str, "float | str | dict"] = Field(default_factory=dict,
                                              description="Détail du calcul : {critère: points, _rationale: {...}}")
    similarity_to_past_go: float = 0.0            # cosine similarity max avec un Go passé
    similar_past_opportunities: list[str] = Field(default_factory=list)  # noms des AO similaires

    # Métadonnées process
    is_urgent: bool = False                        # deadline ≤ 7 jours
    is_new: bool = True                            # première fois qu'on la voit ?
    status: str = "DETECTED"                       # DETECTED / ANALYZING / GO / NO_GO / SUBMITTED
