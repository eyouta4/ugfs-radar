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

import json
from datetime import date

from groq import AsyncGroq, GroqError
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

    return f"""Tu es un analyste senior chez **UGFS North Africa**, société de Private Equity basée à Tunis, spécialisée en finance climatique et impact investing.

═══════════════════════════════════════════════════════
PROFIL UGFS
═══════════════════════════════════════════════════════
**Types acceptés :** asset management, grants, advisory, mandats
**Thématiques :** green (50% priorité), blue (30%), généraliste (20%)

**Géographies :**
  → Primaires (fort intérêt) : {geo_primary}
  → Secondaires (intérêt) : {geo_secondary}
  → Europe (synergie co-investissement) : {geo_europe}
  → HORS SCOPE : North America, Latin America, East Asia/Pacific

**Véhicules actifs UGFS :**
{vehicle_lines}

**Partenaires prioritaires :** {partners_flat}

**Critères de DISQUALIFICATION immédiate :**
{dq_rules}

═══════════════════════════════════════════════════════
MÉTHODE D'ANALYSE OBLIGATOIRE — CHAIN OF THOUGHT
═══════════════════════════════════════════════════════

Tu DOIS raisonner en 3 étapes avant de produire le JSON :

**ÉTAPE 1 — ADMISSIBILITÉ (2-4 phrases)**
Pose-toi ces questions :
  • La deadline est-elle déjà passée (vs aujourd'hui) ?
  • La géographie est-elle 100% hors scope UGFS (Asie hors MENA, Amériques) ?
  • L'éligibilité exclut-elle explicitement les fonds / asset managers ?
  • Est-ce un RFP pour cabinet de conseil individuel ?
  → Conclure : "Admissible" ou "DISQUALIFIÉ : [raison]"

**ÉTAPE 2 — ALIGNEMENT UGFS (4-6 phrases)**
  • Thème : green (énergie, climat, CO2), blue (eau, océan, maritime), généraliste ?
  • Véhicule UGFS le plus adapté : TGF / Blue Bond / Seed of Change / NEW ERA / Musanada ?
  • Géographie : primaire (Tunisie/Maghreb/MENA), secondaire (SSA), Europe, ou autre ?
  • Partenaires mentionnés parmi nos prioritaires ?
  • Ticket size si précisé — dans la sweet spot (500K-50M USD) ?

**ÉTAPE 3 — RECOMMANDATION (1-3 phrases)**
  → GO si : véhicule UGFS clair ET géographie primaire/secondaire ET deadline réaliste
  → BORDERLINE si : alignement partiel, mérite exploration, mais incertitudes
  → NO_GO si : DQ ou trop éloigné du profil UGFS
  → Justifier brièvement la recommandation

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
# Client Groq
# ============================================================

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY non configurée")
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def _call_llm(messages: list[dict], temperature: float = 0.15) -> str:
    """Appel LLM avec retry exponentiel."""
    settings = get_settings()
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type(GroqError),
        reraise=True,
    ):
        with attempt:
            response = await _get_client().chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=temperature,
                max_tokens=2500,          # augmenté pour le raisonnement CoT
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or "{}"
    return "{}"


# ============================================================
# API publique
# ============================================================

async def analyze_opportunity(raw: RawOpportunity) -> AnalyzedOpportunity | None:
    """
    Analyse une opportunité brute via le LLM (chain-of-thought).

    Retourne un AnalyzedOpportunity validé (avec raisonnement CoT), ou None si échec.
    """
    system = _build_system_prompt()
    user = _build_user_prompt(raw)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    try:
        raw_json = await _call_llm(messages)
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

    # Tronquer le raisonnement si trop long
    reasoning = data.get("analyst_reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 2000:
        data["analyst_reasoning"] = reasoning[:2000]

    return data
