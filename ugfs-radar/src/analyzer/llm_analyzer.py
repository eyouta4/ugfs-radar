"""
src/analyzer/llm_analyzer.py — Analyse LLM d'une opportunité brute (chain-of-thought).

Architecture CoT (Chain-of-Thought) :
  1. Le LLM raisonne d'abord en 3 étapes explicites avant de structurer le JSON
     - Étape 1 : admissibilité (disqualification ?)
     - Étape 2 : alignement UGFS (thème, véhicule, géo, partenaires)
     - Étape 3 : recommandation (GO / BORDERLINE / NO_GO + justification)
  2. Le raisonnement est capturé dans `analyst_reasoning` pour auditabilité
  3. Le JSON est ensuite extrait de ce raisonnement → meilleure cohérence

Pourquoi CoT vs extraction directe ?
  - Le LLM "think before he answers" → décisions plus cohérentes
  - On peut auditer le raisonnement de l'agent (Étape 1/2/3 visibles)
  - Réduit les faux positifs : le LLM doit justifier GO avant de l'émettre
  - Compatible avec le scoring déterministe qui suit (LLM extrait des faits,
    on calcule le score nous-mêmes)
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from anthropic import AsyncAnthropic, APIStatusError
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from src.config import (
    AnalyzedOpportunity, Decision, OpportunityType, RawOpportunity, Theme,
    get_settings, get_ugfs_profile,
)
from src.config.logger import get_logger

logger = get_logger(__name__)

# Mots-clés disqualifiant immédiatement une AO sans passer par le LLM.
_NOGO_TITLE_KEYWORDS = [
    "youth only", "young people only", "youth-led", "youth led",
    "ngo only", "ngos only", "civil society only", "non-profit only",
    "nonprofit only", "not-for-profit only", "individuals only", "individual only",
    "canada only", "canadian only", "usa only", "us only", "united states only",
    "latin america only", "east asia only", "pacific only",
    "deadline passed", "applications closed",
    # "closed" intentionally removed — too broad, kills valid AOs
    "instagram", "tiktok",
    # facebook/twitter removed from title filter — may appear as links in valid AO descriptions
]

_NOGO_URL_PATTERNS = [
    "instagram.com", "facebook.com", "twitter.com", "tiktok.com",
    "youtube.com/channel",
    # linkedin.com/posts is intentionally NOT blocked — UGFS finds most opportunities there
]


_GENERIC_TITLES = {
    "actualités", "actualites", "news", "accueil", "home", "homepage",
    "blog", "publications", "articles", "press", "presse", "media",
    "events", "événements", "evenements", "about", "à propos", "a propos",
    "contact", "search", "recherche", "results", "résultats", "resultats",
    "archive", "archives", "feed", "rss", "sitemap", "404", "error",
    "login", "signin", "register", "tenders", "appels d'offres",
    "opportunities", "opportunités", "funding", "grants",
}


def pre_filter(raw: RawOpportunity) -> bool:
    """Retourne True si l'AO est évidemment NO-GO sans besoin du LLM."""
    title = (raw.title or "").strip()
    title_lower = title.lower()
    url_lower = (raw.url or "").lower()
    text_lower = (raw.raw_text or "")[:500].lower()

    # Titre trop court ou générique → faux positif garanti
    if len(title) < 15:
        logger.info("pre_filter_short_title", title=title)
        return True

    # Titre générique (une seule entrée de la liste noire)
    if title_lower in _GENERIC_TITLES:
        logger.info("pre_filter_generic_title", title=title)
        return True

    # Titre sans aucun contenu thématique (1 seul mot, trop ambigu)
    if len(title.split()) <= 1:
        logger.info("pre_filter_single_word_title", title=title)
        return True

    for kw in _NOGO_TITLE_KEYWORDS:
        if kw in title_lower or kw in text_lower:
            logger.info("pre_filter_match", title=raw.title[:60], keyword=kw)
            return True

    for pat in _NOGO_URL_PATTERNS:
        if pat in url_lower:
            logger.info("pre_filter_url", url=raw.url[:80], pattern=pat)
            return True

    return False


# Alias pour rétrocompatibilité
nogo_preflight = pre_filter


# ============================================================
# Pré-scoring par mots-clés (pour trier avant LLM)
# ============================================================

_POSITIVE_KEYWORDS = [
    # Géographies prioritaires (Afrique + Europe synergie)
    "tunisia", "tunisie", "maghreb", "mena", "africa", "afrique",
    "north africa", "afrique du nord", "sub-saharan", "subsaharan",
    "senegal", "morocco", "maroc", "egypt", "egypte", "west africa",
    "east africa", "tanzania", "tanzanie", "sierra leone", "kenya",
    "europe", "european union", "horizon", "afrique subsaharienne",
    # Thèmes énergie / climat (forte priorité TGF — data Teams 2026)
    "climate", "climatique", "green", "vert", "renewable", "renouvelable",
    "clean energy", "energie propre", "solar", "solaire", "wind energy",
    "mini-grid", "mini grid", "off-grid", "energy storage", "bess",
    "energy transition", "transition energetique", "productive use energy",
    "biomass", "biomasse", "clean cooking", "bioenergy", "bioenergie",
    "photovoltaic", "pv", "energy access", "decentralized energy",
    # Thèmes eau / ocean (Blue Bond)
    "blue economy", "ocean", "water", "eau", "maritime",
    "water resilience", "irrigation", "desalination",
    # Thèmes agri (Seed of Change)
    "agritech", "agriculture", "food security", "securite alimentaire",
    "agrifi", "food value chain", "smallholder", "cold chain", "agro",
    # Types d'opportunités prioritaires
    "blended finance", "impact investing", "impact finance",
    "asset management", "fund manager", "gestionnaire de fonds",
    "fund", "fonds", "investment", "investissement",
    "grant", "subvention", "mandate", "mandat",
    "advisory", "technical assistance", "appel a projets",
    "call for proposals", "call for eoi",
    "expression of interest", "manifestation d interet",
    "request for proposals", "rfp", "tdr",
    "project preparation", "co-development", "co-management",
    # Partenaires prioritaires (= signal très fort)
    "giz", "afd", "gcf", "eib", "afdb", "ifc", "convergence",
    "mitigation action facility", "climate kic", "adaptation fund",
    "sifi", "agri-fi", "agrifi", "apia", "cieif", "cfye",
    "green climate fund", "fonds vert", "horizon europe",
    "aecf", "get.invest", "preo", "carbon trust", "gsma",
    "sogrea", "wikistartup", "jif", "aedib", "common fund for commodities",
    "convergence finance", "proparco", "kfw", "undp", "unep",
    "entrepreneurs catalytic hub", "african energy futures",
]


def keyword_prescore(raw: RawOpportunity) -> int:
    """Score rapide par mots-clés pour prioriser les AOs avant analyse LLM."""
    combined = ((raw.title or "") + " " + (raw.raw_text or "")[:1000]).lower()
    return sum(1 for kw in _POSITIVE_KEYWORDS if kw in combined)


# ============================================================
# Construction du prompt chain-of-thought
# ============================================================

def _build_system_prompt() -> str:
    """Prompt système CoT : l'analyste UGFS raisonne avant de structurer."""
    profile = get_ugfs_profile()

    vehicles = profile["vehicles"]
    vehicle_lines = "\n".join(
        f'  - {v["name"]} (code: {v["code"]}) — focus: {v["focus"]}'
        f' — mots-clés: {", ".join(v["keywords"][:5])}'
        for v in vehicles
    )

    partners = profile["priority_partners"]
    partners_flat = ", ".join(
        partners["development_finance"][:15] + partners["partners_seen_in_history"][:10]
    )

    dq_rules = "\n".join(f'  • {r["rule"]}' for r in profile["disqualification_rules"])

    geo_primary = ", ".join(profile["geographies"].get("primary", []))
    geo_secondary = ", ".join(profile["geographies"].get("secondary", [])[:6])
    geo_europe = ", ".join(profile["geographies"].get("europe", [])[:5])

    # GO patterns from real UGFS history
    go_patterns = profile.get("go_patterns", [])
    go_patterns_text = "\n".join(f"  • {p}" for p in go_patterns[:8]) if go_patterns else ""

    return f"""Tu es un analyste senior chez **UGFS North Africa**, gestionnaire de fonds d'impact basé à Tunis, spécialisé en finance climatique et blended finance.

IMPORTANT : UGFS répond aux appels d'offres en tant que **gestionnaire de fonds (fund manager)**, pas comme ONG ou startup.
Son rôle : lever et déployer des capitaux privés via ses véhicules d'investissement thématiques.

═══════════════════════════════════════════════════════
PROFIL UGFS
═══════════════════════════════════════════════════════
**Types acceptés :** asset management, grants pour développement de fonds, advisory, mandats de gestion
**Thématiques :** green (50% priorité), blue (30%), généraliste (20%)

**Géographies :**
  → Primaires (fort intérêt) : {geo_primary}
  → Secondaires (intérêt) : {geo_secondary}
  → Europe (synergie co-investissement) : {geo_europe}
  → HORS SCOPE : North America, Latin America, East Asia/Pacific (sauf si éligibilité Afrique explicite)

**Véhicules actifs UGFS :**
{vehicle_lines}

**Partenaires prioritaires :** {partners_flat}

**Critères de DISQUALIFICATION immédiate :**
{dq_rules}

**Patterns d'opportunités GO identifiés dans l'historique réel UGFS :**
{go_patterns_text}

═══════════════════════════════════════════════════════
MÉTHODE D'ANALYSE OBLIGATOIRE — CHAIN OF THOUGHT
═══════════════════════════════════════════════════════

Tu DOIS raisonner en 3 étapes avant de produire le JSON :

**ÉTAPE 1 — ADMISSIBILITÉ (2-4 phrases)**
  • La deadline est-elle déjà passée (vs aujourd'hui) ?
  • La géographie est-elle 100% hors scope UGFS ?
  • L'éligibilité exclut-elle explicitement les gestionnaires de fonds / asset managers ?
  • Est-ce un RFP pour cabinet de conseil individuel ou programme pour startups/ONG uniquement ?
  → Conclure : "Admissible" ou "DISQUALIFIÉ : [raison précise]"

**ÉTAPE 2 — ALIGNEMENT UGFS (4-6 phrases)**
  • Thème : green (énergie, climat, CO2, renouvelable), blue (eau, océan, marine), généraliste ?
  • Véhicule UGFS le plus adapté : TGF / Blue Bond / Seed of Change / NEW ERA / Musanada ?
  • Géographie : primaire (Tunisie/Maghreb/MENA), secondaire (Afrique SSA), Europe, ou hors scope ?
  • Partenaires mentionnés parmi nos prioritaires (GCF, AFD, GIZ, AfDB, IFC, Mitigation AF, Climate KIC...) ?
  • Ticket size si précisé — sweet spot UGFS 500K-50M USD ?
  • Est-ce que l'AO ressemble aux types d'opportunités soumises historiquement par UGFS ?

**ÉTAPE 3 — RECOMMANDATION (1-3 phrases)**
  → GO si : véhicule UGFS clair ET (géographie primaire OU secondaire OU Europe) ET deadline réaliste ET asset manager éligible
  → BORDERLINE si : alignement partiel, partenaire connu, géographie étendue mais pas disqualifiante, mérite investigation
  → NO_GO si : disqualifié OU type incompatible (startup, ONG uniquement) OU géographie strictement hors scope
  → Justifier avec 1-2 raisons concrètes

Ce raisonnement va dans le champ `analyst_reasoning` du JSON.
Après ce raisonnement, produis le JSON STRICT. Réponds UNIQUEMENT avec le JSON, sans markdown.
"""


def _build_user_prompt(raw: RawOpportunity) -> str:
    """Prompt utilisateur : opportunité + schéma JSON avec analyst_reasoning."""
    today = date.today().isoformat()

    schema_block = """{
  "analyst_reasoning": "string — TON RAISONNEMENT en 3 étapes (Étape 1 Admissibilité → Étape 2 Alignement → Étape 3 Recommandation). Minimum 80 mots.",
  "title": "string (titre normalisé, en français de préférence)",
  "summary_executive": "string (3-4 phrases en français : ce que c'est, qui le porte, pour qui, montant si connu)",
  "opportunity_type": "asset_management" | "grant" | "advisory" | "mandate" | "unknown",
  "theme": "green" | "blue" | "generaliste" | "unknown",
  "geographies": ["liste des pays/régions cibles de l'AO"],
  "sectors": ["secteurs spécifiques : énergie solaire, agriculture, santé, numérique, eau..."],
  "eligibility_summary": "string (qui peut postuler, critères clés d'éligibilité)",
  "deadline": "YYYY-MM-DD ou null si rolling/non précisée",
  "deadline_text_raw": "texte brut original de la deadline",
  "ticket_size_usd": null | integer (montant en USD si mentionné, sinon null),
  "languages": ["fr", "en", "ar"... — langues de soumission acceptées],
  "why_interesting": "string (2-3 raisons concrètes et spécifiques pour UGFS)",
  "preliminary_decision": "GO" | "NO_GO" | "BORDERLINE" | "PENDING",
  "decision_rationale": "string (synthèse en 1-2 phrases de ta recommandation)",
  "partners_mentioned": ["noms institutions/partenaires mentionnés dans le texte"],
  "vehicle_match": "TGF" | "BLUE_BOND" | "SEED_OF_CHANGE" | "NEW_ERA" | "MUSANADA" | null,
  "submission_url": "URL directe vers formulaire de soumission ou null"
}"""

    return f"""Analyse cette opportunité (date d'aujourd'hui : **{today}**).

Commence par ton raisonnement en 3 étapes, puis retourne le JSON conforme au schéma.

━━━ OPPORTUNITÉ ━━━

**Titre :** {raw.title}
**URL :** {raw.url}
**Source :** {raw.source}
**Hint deadline :** {raw.deadline_hint or "non précisé"}

**Texte récupéré :**
\"\"\"
{raw.raw_text[:4000]}
\"\"\"

━━━ FORMAT DE SORTIE JSON STRICT ━━━

{schema_block}

Rappel : commence par `"analyst_reasoning"` avec ton raisonnement CoT complet (étapes 1-2-3).
Réponds uniquement avec le JSON valide, sans aucun texte avant ou après.
"""


# ============================================================
# Clients LLM — Anthropic (principal) + Groq (fallback gratuit)
# ============================================================

_anthropic_client: AsyncAnthropic | None = None
_groq_client = None   # httpx async, pas de SDK


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY non configurée")
        _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


async def _call_anthropic(system: str, user: str, temperature: float = 0.15) -> str:
    """Appel Claude avec retry exponentiel et prompt caching."""
    settings = get_settings()
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type(APIStatusError),
        reraise=True,
    ):
        with attempt:
            response = await _get_anthropic_client().messages.create(
                model=settings.anthropic_model,
                max_tokens=2500,
                system=[{"type": "text", "text": system,
                          "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
            )
            return response.content[0].text or "{}"
    return "{}"


async def _call_groq(system: str, user: str, temperature: float = 0.15) -> str:
    """
    Fallback Groq (Llama 3.3 70B) — API OpenAI-compatible, gratuit.
    https://console.groq.com — 14 400 req/jour, ~30 RPM tier gratuit.

    Retry automatique sur 429 (rate limit) : attend le header retry-after
    ou 65s par défaut, jusqu'à 3 tentatives.
    """
    import httpx
    settings = get_settings()
    groq_key = settings.groq_api_key
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY non configurée")

    payload = {
        "model": settings.groq_model,   # "llama-3.3-70b-versatile"
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 2500,
        "response_format": {"type": "json_object"},  # force JSON
    }
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if r.status_code == 429:
            # Respecter le header retry-after si présent, sinon attendre 65s
            retry_after = int(r.headers.get("retry-after", 65))
            retry_after = max(retry_after, 5)   # toujours ≥ 5s
            logger.warning(
                "groq_rate_limited",
                attempt=attempt,
                retry_after_s=retry_after,
                max_attempts=max_attempts,
            )
            if attempt < max_attempts:
                await asyncio.sleep(retry_after)
                continue
            # Dernière tentative échouée
            r.raise_for_status()
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or "{}"
    raise RuntimeError("Groq: nombre maximum de tentatives dépassé (429 persistant)")


async def _call_llm(system: str, user: str, temperature: float = 0.15) -> str:
    """
    Stratégie : Anthropic (Claude) en priorité, Groq (Llama) en fallback.

    Si Anthropic échoue (crédit épuisé, quota, erreur réseau) → bascule sur Groq.
    Si Groq configuré mais Anthropic absent → Groq directement.
    """
    settings = get_settings()
    has_anthropic = bool(settings.anthropic_api_key)
    has_groq = bool(settings.groq_api_key)

    # Priorité 1 : Anthropic Claude
    if has_anthropic:
        try:
            result = await _call_anthropic(system, user, temperature)
            logger.debug("llm_provider_used", provider="anthropic")
            return result
        except Exception as exc:
            err_str = str(exc)
            # Crédit épuisé ou quota → basculer sur Groq sans retry
            if "credit balance" in err_str or "rate_limit" in err_str or "529" in err_str:
                logger.warning("anthropic_fallback_to_groq", reason=err_str[:120])
            else:
                raise  # Erreur inattendue → propager

    # Priorité 2 : Groq Llama (fallback gratuit)
    if has_groq:
        result = await _call_groq(system, user, temperature)
        logger.info("llm_provider_used", provider="groq_fallback")
        return result

    raise RuntimeError("Aucun LLM disponible — configure ANTHROPIC_API_KEY ou GROQ_API_KEY")


# ============================================================
# API publique
# ============================================================

async def analyze_opportunity(raw: RawOpportunity) -> AnalyzedOpportunity | None:
    """
    Analyse une opportunité brute via le LLM (chain-of-thought).

    Applique pre_filter avant l'appel LLM pour économiser les tokens.
    Retourne un AnalyzedOpportunity validé, ou None si échec.
    """
    if pre_filter(raw):
        return AnalyzedOpportunity(
            title=raw.title,
            summary_executive="Disqualifié par le filtre automatique (mots-clés NO-GO détectés).",
            opportunity_type=OpportunityType.UNKNOWN,
            theme=Theme.UNKNOWN,
            eligibility_summary="Non éligible selon les critères UGFS (filtre préliminaire).",
            why_interesting="N/A — disqualifié avant analyse LLM.",
            preliminary_decision=Decision.NO_GO,
            decision_rationale="DISQUALIFIED: no-go preflight filter matched.",
        )

    system = _build_system_prompt()
    user = _build_user_prompt(raw)

    try:
        raw_json = await _call_llm(system, user)
    except Exception as exc:
        logger.warning("llm_call_failed", title=raw.title[:60], error=str(exc))
        return None

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning("llm_json_invalid", title=raw.title[:60], error=str(exc), raw=raw_json[:300])
        return None

    reasoning = data.get("analyst_reasoning", "")
    if reasoning:
        logger.debug("cot_reasoning", title=raw.title[:50], reasoning_len=len(reasoning))

    data = _coerce(data)

    try:
        analyzed = AnalyzedOpportunity(**data)
    except ValidationError as exc:
        logger.warning("llm_pydantic_invalid", title=raw.title[:60], errors=exc.errors()[:3])
        return None

    return analyzed


def _coerce(data: dict) -> dict:
    """Normalise la sortie LLM pour compatibilité Pydantic."""
    type_val = (data.get("opportunity_type") or "").lower()
    if type_val not in {e.value for e in OpportunityType}:
        data["opportunity_type"] = "unknown"
    else:
        data["opportunity_type"] = type_val

    theme_val = (data.get("theme") or "").lower()
    if theme_val not in {e.value for e in Theme}:
        data["theme"] = "unknown"
    else:
        data["theme"] = theme_val

    decision_val = (data.get("preliminary_decision") or "").upper()
    if decision_val not in {e.value for e in Decision}:
        data["preliminary_decision"] = "PENDING"
    else:
        data["preliminary_decision"] = decision_val

    for key in ("geographies", "sectors", "languages", "partners_mentioned"):
        v = data.get(key)
        if isinstance(v, str):
            data[key] = [s.strip() for s in v.split(",") if s.strip()]
        elif v is None:
            data[key] = []

    ticket = data.get("ticket_size_usd")
    if isinstance(ticket, str):
        digits = "".join(c for c in ticket if c.isdigit())
        data["ticket_size_usd"] = int(digits) if digits else None

    vm = data.get("vehicle_match")
    valid_vehicles = {"TGF", "BLUE_BOND", "SEED_OF_CHANGE", "NEW_ERA", "MUSANADA"}
    if vm and vm.upper() not in valid_vehicles:
        data["vehicle_match"] = None
    elif vm:
        data["vehicle_match"] = vm.upper()

    reasoning = data.get("analyst_reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 2000:
        data["analyst_reasoning"] = reasoning[:2000]

    return data
