"""
src/analyzer/scoring.py — Scoring déterministe d'une opportunité.

Architecture du scoring
-----------------------
Le LLM (llm_analyzer.py) extrait des FAITS structurés (géographies, thème,
deadline, etc.). Le scoring est entièrement DÉTERMINISTE et reproductible :
on ne demande JAMAIS au LLM de "noter" l'opportunité — on calcule nous-mêmes
à partir des faits qu'il a extraits, en pondérant selon `ugfs_profile.yaml`.

Pourquoi ? Parce qu'un LLM n'est pas stable sur la notation : on aurait des
scores différents d'une exécution à l'autre, et impossible d'expliquer aux
analystes UGFS pourquoi un AO est à 72/100. Ici on a un breakdown traçable :

    score_breakdown = {
        "geography_match": 20,
        "theme_match": 18,
        "vehicle_match": 25,
        "partner_match": 0,
        "deadline_feasibility": 8,
        "ticket_in_sweet_spot": 5,
        "language_match": 5,
        "similarity_to_past_go": 0,
    }
    score = 81

Les poids sont chargés depuis :
  1. La table `scoring_weights` (version active) si elle existe → boucle d'apprentissage
  2. Sinon `data/ugfs_profile.yaml` → valeurs initiales

Règles de disqualification : si une règle DQ matche, score = 0 et statut = NO_GO.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.config import (
    AnalyzedOpportunity,
    Decision,
    RawOpportunity,
    ScoredOpportunity,
)
from src.config.logger import get_logger
from src.config.settings import get_settings, get_ugfs_profile
from src.storage.repository import compute_fingerprint

logger = get_logger(__name__)


# ============================================================
# Helpers de matching
# ============================================================

def _normalize(text: str) -> str:
    """Normalise pour matching insensible à la casse + accents."""
    import unicodedata
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_accents.lower().strip()


def _any_keyword_in(text: str, keywords: list[str]) -> bool:
    """True si au moins un keyword apparaît dans `text` (case-insensitive)."""
    t = _normalize(text)
    return any(_normalize(k) in t for k in keywords if k)


def _list_intersects(items: list[str], targets: list[str]) -> list[str]:
    """Retourne les éléments de `items` qui matchent (substring) un target."""
    matches = []
    norm_targets = [_normalize(t) for t in targets if t]
    for item in items:
        ni = _normalize(item)
        for nt in norm_targets:
            if nt in ni or ni in nt:
                matches.append(item)
                break
    return matches


# ============================================================
# Critères de disqualification
# ============================================================

def check_disqualification(
    analyzed: AnalyzedOpportunity,
    profile: dict[str, Any],
) -> tuple[bool, str | None]:
    """
    Vérifie les règles de DQ. Retourne (is_disqualified, reason).

    Règles tirées du profil + cas vus dans l'historique UGFS.
    """
    today = date.today()

    # 1. Deadline déjà passée
    if analyzed.deadline is not None and analyzed.deadline < today:
        return True, f"Deadline dépassée ({analyzed.deadline.isoformat()})"

    # 2. Géographie strictement hors scope
    geo_excluded_raw = profile["geographies"].get("excluded_strict", [])
    # Le YAML contient des entrées comme "North America (sauf si éligibilité Afrique)"
    # → on extrait juste la partie avant la parenthèse pour le matching
    geo_excluded = [_normalize(g.split("(")[0]) for g in geo_excluded_raw]
    if analyzed.geographies:
        # Si TOUTES les géographies de l'opportunité sont dans l'exclusion stricte
        all_excluded = all(
            any(ex and ex in _normalize(g) for ex in geo_excluded)
            for g in analyzed.geographies
        )
        if all_excluded:
            return True, f"Géographies hors scope: {', '.join(analyzed.geographies)}"

    # 3. Éligibilité incompatible (le LLM a tagué un type inadapté)
    elig = _normalize(analyzed.eligibility_summary or "")
    incompatible_eligibility_signals = [
        "individuals only",
        "individus uniquement",
        "youth-led organizations",
        "youth groups only",
        "consultancy firm",
        "cabinet de conseil uniquement",
        "individual consultant",
        "local groups only",
        "groupes locaux uniquement",
    ]
    for signal in incompatible_eligibility_signals:
        if signal in elig:
            return True, f"Éligibilité incompatible (UGFS = asset manager) : « {signal} »"

    return False, None


# ============================================================
# Calcul des sous-scores
# ============================================================

def score_geography(geographies: list[str], profile: dict[str, Any]) -> tuple[int, str]:
    """
    Score géographie : full points si une géo primaire matche,
    50% si secondaire, 25% si Europe, 0 sinon.
    """
    if not geographies:
        return 0, "Aucune géographie identifiée"

    primary = profile["geographies"].get("primary", [])
    secondary = profile["geographies"].get("secondary", [])
    europe = profile["geographies"].get("europe", [])

    matches_primary = _list_intersects(geographies, primary)
    if matches_primary:
        return 100, f"Géographie primaire UGFS : {', '.join(matches_primary)}"

    matches_secondary = _list_intersects(geographies, secondary)
    if matches_secondary:
        return 50, f"Géographie secondaire (Afrique élargie) : {', '.join(matches_secondary)}"

    matches_europe = _list_intersects(geographies, europe)
    if matches_europe:
        return 25, f"Géographie Europe (synergie possible) : {', '.join(matches_europe)}"

    return 10, f"Géographies non prioritaires : {', '.join(geographies[:3])}"


def score_theme(theme_value: str, profile: dict[str, Any]) -> tuple[int, str]:
    """
    Score thème : on aligne avec la pondération du profil.
    `themes` du profil donne {green: 50, blue: 30, generaliste: 20} → on
    normalise sur 100 (le thème dominant = 100, les autres au prorata).
    """
    themes = profile.get("themes", {})
    if not themes:
        return 50, "Pas de pondération thème dans profil"

    max_weight = max(themes.values())
    if max_weight == 0:
        return 0, "Poids thèmes tous nuls"

    weight = themes.get(theme_value, 0)
    pct = round(100 * weight / max_weight)

    if theme_value == "unknown":
        return 30, "Thème non identifié par le LLM"

    return pct, f"Thème '{theme_value}' aligné à {pct}% sur le profil UGFS"


def score_vehicle(
    analyzed: AnalyzedOpportunity,
    raw_text: str,
    profile: dict[str, Any],
) -> tuple[int, str]:
    """
    Score véhicule : 100 si l'AO matche un véhicule actif d'UGFS.
    On regarde d'abord le `vehicle_match` extrait par le LLM, puis fallback
    sur un matching keywords sur le texte brut.
    """
    vehicles = profile.get("vehicles", [])
    if not vehicles:
        return 0, "Aucun véhicule actif dans le profil"

    # 1. Match explicite par le LLM
    if analyzed.vehicle_match:
        for v in vehicles:
            if v.get("code") == analyzed.vehicle_match:
                return 100, f"Match explicite véhicule {v['name']}"

    # 2. Fallback keywords
    text_blob = " ".join([
        analyzed.title or "",
        analyzed.summary_executive or "",
        analyzed.eligibility_summary or "",
        " ".join(analyzed.sectors or []),
        raw_text[:2000] if raw_text else "",
    ])
    for v in vehicles:
        kws = v.get("keywords", [])
        if _any_keyword_in(text_blob, kws):
            return 100, f"Match keywords véhicule {v['name']}"

    return 0, "Aucun véhicule UGFS matché"


def score_partner(partners_mentioned: list[str], profile: dict[str, Any]) -> tuple[int, str]:
    """
    Score partenaires : 100 si un partenaire prioritaire est mentionné.
    """
    if not partners_mentioned:
        return 0, "Aucun partenaire identifié"

    pp = profile.get("priority_partners", {})
    all_priority = []
    for cat in pp.values():
        if isinstance(cat, list):
            all_priority.extend(cat)

    matches = _list_intersects(partners_mentioned, all_priority)
    if matches:
        return 100, f"Partenaire(s) prioritaire(s) : {', '.join(matches[:3])}"
    return 30, f"Partenaires non prioritaires : {', '.join(partners_mentioned[:3])}"


def score_deadline_feasibility(deadline: date | None) -> tuple[int, str]:
    """
    Score deadline : on a le temps de monter un dossier propre ?
      - Pas de deadline (rolling) → 70 pts (on peut planifier)
      - ≥ 30 jours → 100
      - 14-30 jours → 70
      - 7-14 jours → 40
      - < 7 jours → 20 (urgent mais réalisable)
      - Passée → DQ (déjà géré)
    """
    if deadline is None:
        return 70, "Rolling / non précisée — flexibilité pour soumission"

    today = date.today()
    days = (deadline - today).days

    if days >= 30:
        return 100, f"{days} jours → temps confortable"
    if days >= 14:
        return 70, f"{days} jours → réalisable avec coordination"
    if days >= 7:
        return 40, f"{days} jours → court, mobilisation rapide"
    if days >= 0:
        return 20, f"{days} jours → URGENT"
    return 0, f"Deadline dépassée ({deadline.isoformat()})"


def score_ticket(
    ticket_size_usd: int | None,
    profile: dict[str, Any],
) -> tuple[int, str]:
    """
    Score ticket : 100 si dans la sweet spot, 50 si hors mais pas de restriction
    UGFS, 0 si pas d'info exploitable.
    """
    ts = profile.get("ticket_size", {})
    if ts.get("no_restriction"):
        if ticket_size_usd is None:
            return 50, "Ticket non précisé"
        smin = ts.get("sweet_spot_min_usd") or 0
        smax = ts.get("sweet_spot_max_usd") or 10**12
        if smin <= ticket_size_usd <= smax:
            return 100, f"Ticket {ticket_size_usd:,} USD ∈ sweet spot"
        return 50, f"Ticket {ticket_size_usd:,} USD hors sweet spot mais acceptable"
    return 50, "Pas de restriction ticket"


def score_language(languages: list[str], profile: dict[str, Any]) -> tuple[int, str]:
    """
    Score langue : 100 si une langue préférée matche, 50 si acceptable, 0 sinon.
    """
    if not languages:
        return 50, "Langue non identifiée"

    lang_profile = profile.get("languages", {})
    preferred = [_normalize(l) for l in lang_profile.get("preferred", [])]
    acceptable = [_normalize(l) for l in lang_profile.get("acceptable", [])]

    norm_langs = [_normalize(l)[:2] for l in languages]
    if any(l[:2] in [p[:2] for p in preferred] for l in norm_langs):
        return 100, f"Langue préférée : {', '.join(languages)}"
    if any(l[:2] in [a[:2] for a in acceptable] for l in norm_langs):
        return 50, f"Langue acceptable : {', '.join(languages)}"
    return 30, f"Langue hors profil : {', '.join(languages)}"


def score_similarity(similarity_to_past_go: float, profile: dict[str, Any]) -> tuple[int, str]:
    """
    Score similarité : on traduit la cosine sim [0..1] en points [0..100].
    Le boost final (+10 si > seuil) est appliqué au-dessus du score pondéré.
    """
    if similarity_to_past_go <= 0:
        return 0, "Pas de match avec un Go passé"
    pct = int(similarity_to_past_go * 100)
    return pct, f"Similarité {pct}% avec un Go passé"


# ============================================================
# Score global
# ============================================================

def compute_score(
    raw: RawOpportunity,
    analyzed: AnalyzedOpportunity,
    weights: dict[str, float] | None = None,
    similarity_to_past_go: float = 0.0,
    similar_past_titles: list[str] | None = None,
) -> ScoredOpportunity:
    """
    Calcule le score final d'une opportunité.

    Args:
        raw: opportunité brute (du collecteur)
        analyzed: faits extraits par le LLM
        weights: poids actifs (par défaut → profil YAML)
        similarity_to_past_go: cosine similarity max avec un Go passé [0..1]
        similar_past_titles: titres des AO similaires (pour audit)

    Returns:
        ScoredOpportunity avec score, breakdown, fingerprint, statut.
    """
    profile = get_ugfs_profile()
    settings = get_settings()

    if weights is None:
        weights = profile.get("scoring_weights", {})

    # 1. Disqualification ?
    is_dq, dq_reason = check_disqualification(analyzed, profile)

    # 2. Calcul des sous-scores (sur 100 chacun)
    geo_pts, geo_why = score_geography(analyzed.geographies, profile)
    theme_pts, theme_why = score_theme(analyzed.theme.value, profile)
    veh_pts, veh_why = score_vehicle(analyzed, raw.raw_text, profile)
    part_pts, part_why = score_partner(analyzed.partners_mentioned, profile)
    dead_pts, dead_why = score_deadline_feasibility(analyzed.deadline)
    tick_pts, tick_why = score_ticket(analyzed.ticket_size_usd, profile)
    lang_pts, lang_why = score_language(analyzed.languages, profile)
    sim_pts, sim_why = score_similarity(similarity_to_past_go, profile)

    # 3. Pondération
    breakdown = {
        "geography_match": geo_pts * weights.get("geography_match", 0) / 100,
        "theme_match": theme_pts * weights.get("theme_match", 0) / 100,
        "vehicle_match": veh_pts * weights.get("vehicle_match", 0) / 100,
        "partner_match": part_pts * weights.get("partner_match", 0) / 100,
        "deadline_feasibility": dead_pts * weights.get("deadline_feasibility", 0) / 100,
        "ticket_in_sweet_spot": tick_pts * weights.get("ticket_in_sweet_spot", 0) / 100,
        "language_match": lang_pts * weights.get("language_match", 0) / 100,
        "similarity_to_past_go": sim_pts * weights.get("similarity_to_past_go", 0) / 100,
    }
    rationale = {
        "geography_match": geo_why,
        "theme_match": theme_why,
        "vehicle_match": veh_why,
        "partner_match": part_why,
        "deadline_feasibility": dead_why,
        "ticket_in_sweet_spot": tick_why,
        "language_match": lang_why,
        "similarity_to_past_go": sim_why,
    }

    score = round(sum(breakdown.values()))

    # 4. Boost similarité — si similarité > seuil, on push de +10 pts
    if similarity_to_past_go >= settings.similarity_boost_threshold:
        score = min(100, score + settings.similarity_boost_points)
        breakdown["similarity_boost"] = float(settings.similarity_boost_points)
        rationale["similarity_boost"] = (
            f"Boost +{settings.similarity_boost_points} (sim={similarity_to_past_go:.2f})"
        )

    # 5. DQ override
    if is_dq:
        score = 0
        breakdown = {"DISQUALIFIED": 0.0}
        rationale = {"DISQUALIFIED": dq_reason or "Règle DQ"}

    # 6. Marquer urgent si deadline proche
    is_urgent = False
    if analyzed.deadline is not None:
        days = (analyzed.deadline - date.today()).days
        is_urgent = 0 <= days <= settings.urgent_deadline_days

    # 7. Statut initial
    status = "NO_GO" if is_dq else "DETECTED"

    # 8. Décision préliminaire si LLM n'en a pas mis de claire
    if is_dq:
        analyzed.preliminary_decision = Decision.NO_GO
        analyzed.decision_rationale = (analyzed.decision_rationale or "")[:200] + f" | DQ: {dq_reason}"
    elif score >= 70:
        analyzed.preliminary_decision = Decision.GO
    elif score >= 50:
        analyzed.preliminary_decision = Decision.BORDERLINE
    elif score >= 0 and analyzed.preliminary_decision == Decision.PENDING:
        analyzed.preliminary_decision = Decision.NO_GO

    fingerprint = compute_fingerprint(raw.title, raw.url, analyzed.deadline)

    scored = ScoredOpportunity(
        fingerprint=fingerprint,
        raw=raw,
        analyzed=analyzed,
        score=score,
        score_breakdown={
            **{k: round(v, 2) for k, v in breakdown.items()},
            "_rationale": rationale,  # type: ignore[dict-item]
        },
        similarity_to_past_go=similarity_to_past_go,
        similar_past_opportunities=similar_past_titles or [],
        is_urgent=is_urgent,
        is_new=True,
        status=status,
    )

    logger.debug(
        "scored_opportunity",
        fingerprint=fingerprint[:8],
        title=raw.title[:60],
        score=score,
        is_dq=is_dq,
        is_urgent=is_urgent,
    )
    return scored
