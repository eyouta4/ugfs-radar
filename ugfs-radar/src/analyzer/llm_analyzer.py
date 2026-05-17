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
from typing import Any

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

# Fragments de chemin d'URL qui indiquent une page non-actionnable
# (page pays, webinaire, événement, catégorie générique)
_NOGO_URL_PATH_FRAGMENTS = [
    "/webinars/", "/webinar/",               # conférences/webinaires
    "/events/event/", "pathfinder.org/events",  # agendas événements
    "/country/",                             # pages pays Adaptation Fund, etc.
    "wearevuka.com/investor-projects/",      # annuaire fonds
    "federalgrantsinfo.com",                 # site agrégateur non spécialisé
]

# Patterns dans le TITRE qui signalent un article de presse ou annonce non-actionnable
_LIKELY_NEWS_TITLE_PATTERNS = [
    "semi-finalists announced",
    "welcomes new accredited",
    "designated as headquarters",
    " expands into ",
    "boosts clean energy",          # "EU boosts..." = article de presse
    "receives €",                   # "Tunisia receives €..." = article de presse
    "portfolio of $", "portefeuille de",
    ": homepage", "homepage",
    "to expand into regional",
    "announces new ",
    "announces the ",
    " governance: ",
    "gouvernance climatique",
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

    # URL de page webinaire ou événement non-actionnable
    for frag in _NOGO_URL_PATH_FRAGMENTS:
        if frag in url_lower:
            # Exception : si le titre contient "call for proposals" ou "appel" → laisser passer
            if not any(x in title_lower for x in ["call for proposals", "appel à projets",
                                                   "appel a projets", "expression of interest",
                                                   "request for proposals", "rfp", "eoi"]):
                logger.info("pre_filter_url_path", url=raw.url[:80], fragment=frag)
                return True

    # Homepage (URL racine du domaine sans chemin significatif)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw.url or "")
        path = parsed.path.rstrip("/")
        if path in ("", "/") and parsed.netloc:
            logger.info("pre_filter_homepage", url=raw.url[:80])
            return True
    except Exception:
        pass

    # Titre = pattern d'article de presse (non-actionnable direct)
    for pat in _LIKELY_NEWS_TITLE_PATTERNS:
        if pat in title_lower:
            logger.info("pre_filter_news_title", title=title[:80], pattern=pat)
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
    """Prompt système CoT compact (~800 tokens) — économise TPM sur Groq/Cerebras."""
    profile = get_ugfs_profile()

    # Véhicules : juste nom + code + 3 mots-clés (vs 5)
    vehicle_lines = "\n".join(
        f"  - {v['name']} (code={v['code']}): {v['focus'][:80]}"
        for v in profile["vehicles"]
    )

    # Partenaires : top 12 seulement (vs 25)
    dev_fin = profile["priority_partners"]["development_finance"][:12]
    partners_flat = ", ".join(dev_fin)

    return f"""Tu es analyste senior chez **UGFS North Africa**, fund manager d'impact à Tunis.
UGFS répond aux AOs comme GESTIONNAIRE DE FONDS (pas ONG/startup) — lève et déploie du capital privé.

**Types acceptés :** asset_management, grant (pour développer un fonds), advisory, mandate
**Thématiques :** green (50%) / blue (30%) / generaliste (20%)
**Géographies :**
  - Primaires : Tunisia, Maghreb, MENA, Afrique, Sénégal, Tanzanie
  - Secondaires : Afrique SSA (Kenya, Morocco, Egypt, Sierra Leone, Nigeria, Ghana...)
  - Europe : EU, France, Germany, Netherlands... (synergie co-investissement)
  - HORS SCOPE strict : North America only, Latin America only, East Asia only

**Véhicules UGFS actifs :**
{vehicle_lines}

**Partenaires prioritaires (signal fort) :** {partners_flat}

═══════════════════════════════════════════════════════
MÉTHODE OBLIGATOIRE — Chain of Thought en 4 étapes
═══════════════════════════════════════════════════════

**ÉTAPE 0 — TYPE DE CONTENU (critique)** Identifie d'abord :
  ✅ APPEL OUVERT (Call for Proposals / EoI / RFP / Appel à Projets / Apply now) → opportunity_type=grant/asset_management/advisory/mandate
  ❌ ARTICLE DE PRESSE / annonce d'une décision ("EU announces", "GCF welcomes", "designated as") → type=unknown, decision=NO_GO
  ❌ ÉVÉNEMENT / WEBINAIRE / CONFERENCE / DIALOGUE → type=unknown, decision=NO_GO
  ❌ PAGE GÉNÉRIQUE (homepage, page pays, annuaire) → type=unknown, decision=NO_GO
  ❌ RÉSULTATS d'un appel passé ("Semi-finalists announced", "Winners") → type=unknown, decision=NO_GO
  ⚠️ Un article parlant d'une opportunité n'est PAS l'opportunité.

**ÉTAPE 1 — ADMISSIBILITÉ**
  • Deadline passée ? Géo 100% hors scope ? Réservé ONG/jeunes/individus/startups ?
  → "Admissible" ou "DISQUALIFIÉ : [raison]"

**ÉTAPE 2 — ALIGNEMENT UGFS**
  • Thème ? Véhicule UGFS approprié (TGF/BLUE_BOND/SEED_OF_CHANGE/NEW_ERA/MUSANADA) ?
  • Géographie (primaire/secondaire/europe) ? Partenaires connus mentionnés ?
  • Ressemble aux soumissions UGFS historiques (APIA, Climate KIC, A4FM, SOGREA, PREO) ?

**ÉTAPE 3 — RECOMMANDATION**
  → GO : véhicule clair + géo OK + deadline réaliste + fund manager éligible + APPEL OUVERT
  → BORDERLINE : alignement partiel, mérite investigation
  → NO_GO : DQ ou type incompatible

Output : JSON strict (pas de markdown), commencer par `analyst_reasoning` (étapes 0→3, min 80 mots).

⚠️ EXEMPLES ANTI-FAUX-POSITIFS (à mémoriser) :
  - "EU boosts clean energy with €35M grant" → unknown, NO_GO (article)
  - "GCF welcomes new Accredited Entities" → unknown, NO_GO (annonce)
  - "GCF Regional Dialogue MENA" → unknown, NO_GO (événement)
  - "Semi-Finalists Announced: A4FM" → unknown, NO_GO (appel fermé)
  - "Country – Adaptation Fund /country/RG/" → unknown, NO_GO (page pays)
  - "Appel à Projets APIA Margines 2026" → grant, peut être GO
  - "Call for proposals | ACCF Portal" → grant, GO
  - "Blended Finance Accelerator for Fund Managers — Apply" → grant, GO
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
{raw.raw_text[:1800]}
\"\"\"

━━━ FORMAT DE SORTIE JSON STRICT ━━━

{schema_block}

Rappel : commence par `"analyst_reasoning"` avec ton raisonnement CoT complet (étapes 1-2-3).
Réponds uniquement avec le JSON valide, sans aucun texte avant ou après.
"""


# ============================================================
# Clients LLM — chaîne de fallback :
#   Anthropic (Claude)  →  Groq (Llama 8B fast)  →  Cerebras (Llama 70B)  →  Gemini Flash
# ============================================================

_anthropic_client: AsyncAnthropic | None = None
_groq_client = None   # httpx async, pas de SDK

# Cache de session : si une API échoue avec une erreur durable (crédit épuisé,
# quota journalier), on ne la rappelle pas pour tout le run.
_DISABLED_PROVIDERS: set[str] = set()


def _disable_provider(name: str, reason: str) -> None:
    """Marque un provider comme désactivé pour le reste du run."""
    if name not in _DISABLED_PROVIDERS:
        _DISABLED_PROVIDERS.add(name)
        logger.warning("llm_provider_disabled", provider=name, reason=reason[:200])


def _is_provider_disabled(name: str) -> bool:
    return name in _DISABLED_PROVIDERS


def reset_provider_cache() -> None:
    """Reset le cache de providers désactivés (utile entre runs)."""
    _DISABLED_PROVIDERS.clear()


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
                max_tokens=2000,
                system=[{"type": "text", "text": system,
                          "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
            )
            return response.content[0].text or "{}"
    return "{}"


async def _call_openai_compatible(
    api_name: str,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.15,
    support_json_mode: bool = True,
) -> str:
    """
    Appel d'un endpoint OpenAI-compatible (Groq, Cerebras, etc.).
    Gère 429 avec retry exponentiel + cap sur retry_after (configurable).
    Si 429 persistant ou retry_after > cap → désactive le provider pour le run.
    """
    import httpx
    settings = get_settings()

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 2000,
    }
    if support_json_mode:
        payload["response_format"] = {"type": "json_object"}

    max_attempts = 3
    cap = settings.llm_max_retry_after_s   # ex: 90s

    for attempt in range(1, max_attempts + 1):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if r.status_code == 429:
            retry_after = int(r.headers.get("retry-after", 30))
            # Si l'API demande un délai > cap, c'est un quota journalier
            # → désactiver le provider pour le run au lieu d'attendre des heures
            if retry_after > cap:
                _disable_provider(
                    api_name,
                    f"quota dépassé (retry_after={retry_after}s > cap {cap}s)",
                )
                raise RuntimeError(
                    f"{api_name}: quota journalier épuisé "
                    f"(retry_after={retry_after}s)"
                )
            retry_after = max(retry_after, 5)
            logger.warning(
                f"{api_name}_rate_limited",
                attempt=attempt,
                retry_after_s=retry_after,
                max_attempts=max_attempts,
            )
            if attempt < max_attempts:
                await asyncio.sleep(retry_after)
                continue
            r.raise_for_status()

        # Détection erreur "quota épuisé" via le body (variable selon provider)
        if r.status_code in (401, 402, 403):
            err_body = r.text[:300]
            if any(k in err_body.lower() for k in (
                "quota", "credit", "insufficient", "exceeded", "limit"
            )):
                _disable_provider(api_name, err_body)
                raise RuntimeError(f"{api_name}: quota/crédit épuisé — {err_body}")

        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or "{}"

    raise RuntimeError(f"{api_name}: rate-limit persistant après {max_attempts} tentatives")


async def _call_groq(system: str, user: str, temperature: float = 0.15) -> str:
    """Fallback Groq — Llama 3.1 8B Instant par défaut (30 RPM, 30K TPM)."""
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY non configurée")
    return await _call_openai_compatible(
        api_name="groq",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        system=system, user=user, temperature=temperature,
    )


async def _call_cerebras(system: str, user: str, temperature: float = 0.15) -> str:
    """Fallback Cerebras — Llama 3.3 70B (60 RPM gratuit)."""
    settings = get_settings()
    if not settings.cerebras_api_key:
        raise RuntimeError("CEREBRAS_API_KEY non configurée")
    return await _call_openai_compatible(
        api_name="cerebras",
        base_url="https://api.cerebras.ai/v1/chat/completions",
        api_key=settings.cerebras_api_key,
        model=settings.cerebras_model,
        system=system, user=user, temperature=temperature,
        support_json_mode=False,   # Cerebras ne supporte pas tous les modèles JSON mode
    )


async def _call_gemini(system: str, user: str, temperature: float = 0.15) -> str:
    """Fallback Google Gemini — gemini-1.5-flash (15 RPM, 1500 RPD, 1M TPM)."""
    import httpx
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY non configurée")

    # Gemini API native (non OpenAI-compatible)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system}\n\n---\n\n{user}"}]}
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload)
    if r.status_code == 429:
        _disable_provider("gemini", "rate limit Gemini")
        raise RuntimeError("Gemini: rate limit atteint")
    r.raise_for_status()
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"] or "{}"
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini: réponse invalide {str(data)[:200]}")


async def _call_llm(system: str, user: str, temperature: float = 0.15) -> str:
    """
    Stratégie multi-fallback avec circuit breaker (cache de session) :

        1. Anthropic Claude     (premium, si crédit)
        2. Groq Llama 3.1 8B    (gratuit, 30K TPM — défaut rapide)
        3. Cerebras Llama 3.3   (gratuit, 60 RPM — backup haute qualité)
        4. Google Gemini Flash  (gratuit, 15 RPM 1.5K RPD)

    Une fois qu'un provider échoue avec une erreur DURABLE (crédit épuisé,
    quota journalier), il est désactivé pour tout le run via _DISABLED_PROVIDERS.
    → évite de retenter Anthropic 50 fois quand on sait que le crédit = 0.

    Wrapped dans asyncio.wait_for() pour timeout global par AO.
    """
    settings = get_settings()

    providers: list[tuple[str, bool, "callable"]] = [
        ("anthropic", bool(settings.anthropic_api_key),  _call_anthropic),
        ("groq",      bool(settings.groq_api_key),       _call_groq),
        ("cerebras",  bool(settings.cerebras_api_key),   _call_cerebras),
        ("gemini",    bool(settings.gemini_api_key),     _call_gemini),
    ]

    last_error: Exception | None = None

    for name, configured, fn in providers:
        if not configured:
            continue
        if _is_provider_disabled(name):
            continue   # circuit breaker activé pour ce provider
        try:
            result = await asyncio.wait_for(
                fn(system, user, temperature),
                timeout=settings.llm_per_op_timeout_s,
            )
            logger.info("llm_provider_used", provider=name)
            return result
        except asyncio.TimeoutError as exc:
            logger.warning("llm_timeout", provider=name,
                           timeout_s=settings.llm_per_op_timeout_s)
            last_error = exc
            continue
        except Exception as exc:
            err_str = str(exc)
            # Erreurs durables → désactiver le provider pour le run
            durable_signals = (
                "credit balance", "credit_balance",
                "insufficient", "quota", "exceeded",
                "billing", "unauthorized",
            )
            if any(s in err_str.lower() for s in durable_signals):
                _disable_provider(name, err_str)
            logger.warning(
                f"{name}_call_failed",
                reason=err_str[:200],
                next_provider="auto",
            )
            last_error = exc
            continue

    # Aucun provider n'a fonctionné
    raise RuntimeError(
        "Tous les providers LLM ont échoué ou sont désactivés. "
        f"Dernière erreur : {str(last_error)[:200]}"
    )


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

    data = _extract_json(raw_json)
    if data is None:
        logger.warning(
            "llm_json_invalid",
            title=raw.title[:60],
            raw=(raw_json or "")[:300],
        )
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


def _extract_json(text: str) -> dict | None:
    """
    Extrait un JSON depuis la sortie LLM, robuste aux variations :
      - JSON brut
      - JSON enveloppé dans ```json ... ```
      - JSON précédé/suivi de texte explicatif
    Retourne dict ou None si vraiment rien d'extractible.
    """
    import re
    if not text:
        return None

    # Tentative 1 : parse direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Tentative 2 : extraire bloc ```json ... ```
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    # Tentative 3 : trouver le premier { ... } équilibré
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    return None


def _parse_date_from_text(text: str) -> "date | None":
    """
    Extrait une date depuis un texte brut (deadline_text_raw, raw_text, etc.).
    Supporte : "May 19, 2026", "19/05/2026", "2026-05-19", "19 May 2026", etc.
    Retourne la première date future trouvée, ou None.
    """
    import re
    from datetime import date as date_type

    today = date_type.today()
    text = text or ""

    # Format ISO : 2026-05-19
    iso_match = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", text)
    if iso_match:
        try:
            d = date_type(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            if d >= today:
                return d
        except ValueError:
            pass

    # Format européen : 19/05/2026 ou 19.05.2026
    eu_match = re.search(r"\b(0[1-9]|[12]\d|3[01])[./](0[1-9]|1[0-2])[./](20\d{2})\b", text)
    if eu_match:
        try:
            d = date_type(int(eu_match.group(3)), int(eu_match.group(2)), int(eu_match.group(1)))
            if d >= today:
                return d
        except ValueError:
            pass

    # Format anglais : May 19, 2026 / 19 May 2026 / May 2026
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    # "May 19, 2026" or "May 19 2026"
    month_day_year = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2}),?\s+(20\d{2})\b",
        text.lower()
    )
    if month_day_year:
        try:
            m = months[month_day_year.group(1)]
            d = date_type(int(month_day_year.group(3)), m, int(month_day_year.group(2)))
            if d >= today:
                return d
        except ValueError:
            pass

    # "19 May 2026"
    day_month_year = re.search(
        r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(20\d{2})\b",
        text.lower()
    )
    if day_month_year:
        try:
            m = months[day_month_year.group(2)]
            d = date_type(int(day_month_year.group(3)), m, int(day_month_year.group(1)))
            if d >= today:
                return d
        except ValueError:
            pass

    return None


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

    # Fallback deadline : si le LLM n'a pas parsé de date mais qu'un texte de deadline
    # est présent (deadline_text_raw), on tente de l'extraire avec notre parser.
    if data.get("deadline") is None:
        raw_dl_text = data.get("deadline_text_raw") or ""
        if raw_dl_text:
            parsed_dl = _parse_date_from_text(raw_dl_text)
            if parsed_dl:
                data["deadline"] = parsed_dl
                logger.info(
                    "deadline_parsed_from_raw_text",
                    raw_text=raw_dl_text[:80],
                    parsed=parsed_dl.isoformat(),
                )

    reasoning = data.get("analyst_reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 2000:
        data["analyst_reasoning"] = reasoning[:2000]

    return data
