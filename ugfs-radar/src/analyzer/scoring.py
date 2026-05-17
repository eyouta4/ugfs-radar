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
    OpportunityType,
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
    Score véhicule : 100 si l'AO matche un véhicule actif d'UGFS ET est actionnable.

    Règle de pondération de l'actionnabilité :
      - opportunity_type connu (grant/asset_management/advisory/mandate) → plein score
      - opportunity_type == unknown (article/event/page générique) → score réduit à 50
    """
    vehicles = profile.get("vehicles", [])
    if not vehicles:
        return 0, "Aucun véhicule actif dans le profil"

    # Facteur d'actionnabilité : réduction si type inconnu (article/event)
    is_actionable = analyzed.opportunity_type not in (
        OpportunityType.UNKNOWN, None
    )
    action_factor = 1.0 if is_actionable else 0.5  # 50% si type inconnu

    # 1. Match explicite par le LLM
    if analyzed.vehicle_match:
        for v in vehicles:
            if v.get("code") == analyzed.vehicle_match:
                pts = round(100 * action_factor)
                suffix = "" if is_actionable else " (type inconnu — réduit)"
                return pts, f"Match explicite véhicule {v['name']}{suffix}"

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
            pts = round(100 * action_factor)
            suffix = "" if is_actionable else " (type inconnu — réduit)"
            return pts, f"Match keywords véhicule {v['name']}{suffix}"

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
# Pondération qualité de source — un analyste 30 ans sait :
# une AO sur le portail officiel d'un DFI est BEAUCOUP plus fiable
# qu'un article LinkedIn ou un agrégateur tiers.
# ============================================================

# Bonus : sources institutionnelles directes (= portail officiel d'un DFI)
_OFFICIAL_SOURCE_DOMAINS = {
    # DFIs primaires UGFS
    "afdb.org": +8, "accf.afdb.org": +10, "projectsportal.afdb.org": +10,
    "afd.fr": +8, "proparco.fr": +8,
    "greenclimate.fund": +6,
    "adaptation-fund.org": +6,
    "convergence.finance": +10,        # partenaire confirmé
    "climate-kic.org": +8, "eit.europa.eu": +8,
    "mitigation-action.org": +8,
    "ec.europa.eu": +6, "europa.eu": +6,
    "ted.europa.eu": +8,                # appels d'offres officiels UE
    "horizoneurope.ec.europa.eu": +8,
    "kfw.de": +6, "kfw-entwicklungsbank.de": +6,
    "ifc.org": +6, "worldbank.org": +6,
    "undp.org": +5, "procurement.undp.org": +8,
    "unep.org": +5,
    "ebrd.com": +8, "ecepp.ebrd.com": +10,  # EBRD tenders
    "get-invest.eu": +8,                 # PREO / GET.invest
    "aecfafrica.org": +8,
    "universalenergyfacility.org": +8,
    # Sources Tunisie / Maghreb officielles
    "apia.com.tn": +10, "apia.tn": +10,  # APIA agriculture Tunisie
    "tunisieindustrie.tn": +8,
    "cieif.org": +8,
    "tunis.giz.de": +8,
    # Sources LinkedIn UGFS-trusted
    "linkedin.com/posts/funds-for-impact": +5,
    "linkedin.com/posts/africagreenembassy": +5,
    "linkedin.com/posts/blendedfinance-developmentfinance": +5,
    "linkedin.com/posts/global-grants-and-opportunities-for-africa-gga": +4,
    "linkedin.com/posts/entrepreneurs-catalyst-hub": +5,
}

# Pénalité : sources d'information (= articles de presse) où l'AO est mentionnée
# mais n'est pas la source directe → souvent du bruit ou de l'ancien
_NEWS_SOURCE_DOMAINS = {
    "esi-africa.com": -8,                # site presse énergie Afrique
    "financialafrik.com": -6,
    "africanmanager.com": -4,             # presse Tunisie (parfois OK)
    "findevgateway.org": -5,              # agrégat news
    "devex.com": -3,                      # peut être OK si call direct
    "africaagriculturalnetwork.com": -5,
    "africanleadershipmagazine.co.uk": -8,
    "news.fundsforngos.org": -5,
    "opportunitiesforyouth.org": -8,      # cible jeunes, pas fund managers
    "fundsforngos.org": -3,               # peut être OK
    "federalgrantsinfo.com": -8,           # spam agrégat
    "wearevuka.com": -8,                  # annuaire fonds (pas d'appels)
    "tenderimpulse.com": -3,              # tenders publics (parfois OK)
    "x.com": -6, "twitter.com": -6,        # généralement bruit
    "scouts.yutori.com": -10,              # outil de veille tiers
    "gouv.ci": -6,                         # site gouv pour news, pas AOs
}


def score_source_quality(url: str, source_kind: str | None = None) -> tuple[int, str]:
    """
    Ajustement déterministe basé sur la fiabilité de la source.
    Un analyste UGFS expérimenté sait reconnaître :
    - Source officielle (DFI, agence publique) → +5 à +10
    - LinkedIn account spécialisé connu → +3 à +5
    - Site presse / agrégateur → -3 à -10
    - Tweet, scout tiers, page générique → -6 à -10

    Retourne (delta_points, reason). Le delta s'ajoute APRÈS le scoring pondéré.
    """
    if not url:
        return 0, "URL absente"
    url_lower = url.lower()

    # Test domaines officiels (match plus long en priorité)
    for domain, delta in sorted(
        _OFFICIAL_SOURCE_DOMAINS.items(), key=lambda x: -len(x[0])
    ):
        if domain in url_lower:
            return delta, f"Source officielle {domain} (+{delta}pts)"

    # Test domaines presse / agrégateur
    for domain, delta in sorted(
        _NEWS_SOURCE_DOMAINS.items(), key=lambda x: -len(x[0])
    ):
        if domain in url_lower:
            return delta, f"Source presse/agrégat {domain} ({delta:+d}pts)"

    # Aucun match : source inconnue, neutre
    return 0, "Source inconnue (aucun ajustement)"


# ============================================================
# Estimation de l'effort de soumission (un vétéran 30 ans sait :
# une RFP GCF = 6 semaines de travail, un EoI = 2 jours)
# ============================================================

def estimate_effort_days(
    opp_type: str | None,
    title: str,
    eligibility: str,
) -> tuple[int, str]:
    """
    Estime le nombre de jours-homme nécessaires pour soumettre.
    Heuristique basée sur l'expérience UGFS — affinée par RL.

    Returns: (days, level) où level = "low" | "medium" | "high"
    """
    if not opp_type:
        return 5, "medium"

    title_lower = (title or "").lower()
    elig_lower = (eligibility or "").lower()

    # Expression d'intérêt / Concept note → effort léger
    if any(k in title_lower for k in ("expression of interest", "manifestation d'intérêt",
                                       "concept note", "manifestation interet")):
        return 3, "low"

    # RFP / Mandate / GCF readiness → gros dossier
    if any(k in title_lower for k in ("readiness", "rfp", "request for proposals",
                                       "fund manager", "asset manager")):
        return 25, "high"

    # GCF / Adaptation Fund (toujours lourd)
    if any(k in title_lower for k in ("green climate fund", "gcf", "adaptation fund")):
        return 30, "high"

    # Grant standard → moyen
    if opp_type == "grant":
        return 8, "medium"

    # Advisory / TA → court
    if opp_type in ("advisory", "technical_assistance"):
        return 5, "medium"

    # Asset management (mandate) → toujours lourd
    if opp_type in ("asset_management", "mandate"):
        return 20, "high"

    return 5, "medium"


# ============================================================
# Estimation probabilité de gain (calibré sur historique UGFS)
# ============================================================

def estimate_win_probability(
    score: int,
    similarity_to_past_go: float,
    has_priority_partner: bool,
    vehicle_clear: bool,
) -> tuple[int, str]:
    """
    Probabilité estimée de gagner cette AO (0-100%).
    Un vétéran UGFS sait :
    - Score >85 + partenaire connu + véhicule clair → ~25-35% (toujours compétitif)
    - Score 60-85 → ~10-20%
    - Score <60 → <5%

    Calibration affinée par RL via feedback UGFS.
    """
    base = 0
    if score >= 85: base = 25
    elif score >= 75: base = 17
    elif score >= 65: base = 10
    elif score >= 50: base = 6
    else: base = 2

    # Bonus si très similaire à un GO passé (UGFS a déjà gagné un cas similaire)
    if similarity_to_past_go >= 0.85:
        base += 8
    elif similarity_to_past_go >= 0.75:
        base += 4

    # Bonus partenaire connu (relation établie)
    if has_priority_partner:
        base += 5

    # Bonus véhicule clairement adapté
    if vehicle_clear:
        base += 3

    base = min(45, base)   # plafond réaliste

    if base >= 25:
        return base, "Forte (relation + match clair)"
    if base >= 15:
        return base, "Modérée (à investiguer)"
    if base >= 8:
        return base, "Faible (compétition probable)"
    return base, "Très faible (en dehors du sweet spot)"


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

    # 3b. Pénalité "non-actionnable" : si le LLM a identifié un type inconnu
    # (article de presse, événement, page générique), réduire le score.
    # La réduction est progressive selon la décision LLM :
    #   - LLM dit NO_GO + type unknown → -20pts (probablement un article)
    #   - LLM dit BORDERLINE + type unknown → -10pts
    #   - LLM dit GO + type unknown → 0pts (LLM a quand même validé)
    if analyzed.opportunity_type == OpportunityType.UNKNOWN:
        llm_decision = analyzed.preliminary_decision
        if llm_decision == Decision.NO_GO:
            penalty = 20
        elif llm_decision == Decision.BORDERLINE:
            penalty = 10
        else:
            penalty = 5  # type unknown mais LLM dit GO — petite pénalité
        score = max(0, score - penalty)
        breakdown["type_unknown_penalty"] = float(-penalty)
        rationale["type_unknown_penalty"] = (
            f"Pénalité -{penalty}pts : type inconnu (article/event/page générique probable)"
        )

    # 3c. Ajustement qualité de source (un vétéran sait : APIA officiel vs LinkedIn random)
    src_delta, src_why = score_source_quality(raw.url, getattr(raw, "source_kind", None))
    if src_delta != 0:
        score = max(0, min(100, score + src_delta))
        breakdown["source_quality"] = float(src_delta)
        rationale["source_quality"] = src_why

    # 4. Boost similarité — si similarité > seuil, on push de +10 pts
    if similarity_to_past_go >= settings.similarity_boost_threshold:
        score = min(100, score + settings.similarity_boost_points)
        breakdown["similarity_boost"] = float(settings.similarity_boost_points)
        rationale["similarity_boost"] = (
            f"Boost +{settings.similarity_boost_points} (sim={similarity_to_past_go:.2f})"
        )

    # 4b. Insights vétéran : effort estimé + probabilité de win
    # (le score métier reste 0-100, ces métriques s'affichent à part dans l'Excel)
    effort_days, effort_level = estimate_effort_days(
        analyzed.opportunity_type.value if analyzed.opportunity_type else None,
        analyzed.title,
        analyzed.eligibility_summary,
    )
    has_known_partner = part_pts >= 70   # match partenaire prioritaire
    vehicle_clear = veh_pts >= 70 and analyzed.vehicle_match is not None
    win_prob, win_label = estimate_win_probability(
        score=score,
        similarity_to_past_go=similarity_to_past_go,
        has_priority_partner=has_known_partner,
        vehicle_clear=vehicle_clear,
    )
    breakdown["effort_days_estimate"] = float(effort_days)
    breakdown["win_probability_pct"] = float(win_prob)
    rationale["effort_estimate"] = f"Effort ~{effort_days}j ({effort_level})"
    rationale["win_probability"] = f"{win_prob}% — {win_label}"

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
