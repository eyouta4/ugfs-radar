"""
src/analyzer/llm_analyzer.py — Analyse LLM d'une opportunité brute.

On utilise Groq (Llama 3.3 70B, gratuit) pour produire un AnalyzedOpportunity
structuré à partir d'un RawOpportunity. Le prompt est précisément calibré sur
le profil UGFS (chargé depuis ugfs_profile.yaml).

Le LLM est forcé en mode JSON strict via response_format={"type": "json_object"}.
On valide ensuite le JSON via Pydantic. Si le JSON est invalide, on retry une fois
avec un message d'erreur explicite, sinon on log et on skip.
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
# Construction du prompt
# ============================================================

def _build_system_prompt() -> str:
    """Prompt système : positionne le LLM comme analyste UGFS senior."""
    profile = get_ugfs_profile()

    vehicles = profile["vehicles"]
    vehicle_lines = "\n".join(
        f'  - {v["name"]} (code: {v["code"]}) — focus: {v["focus"]} — keywords: {", ".join(v["keywords"][:4])}'
        for v in vehicles
    )

    partners = profile["priority_partners"]
    partners_flat = ", ".join(
        partners["development_finance"][:15] + partners["partners_seen_in_history"][:10]
    )

    dq_rules = "\n".join(f'  - {r["rule"]}' for r in profile["disqualification_rules"])

    return f"""Tu es un analyste senior chez **UGFS North Africa**, société de Private Equity basée à Tunis.

UGFS investit dans :
- **Types** : Asset Management, Grants, Advisory, Mandats
- **Thématiques** : Green (priorité {profile['themes']['green']}%), Blue ({profile['themes']['blue']}%), Généraliste ({profile['themes']['generaliste']}%)
- **Géographies** :
  - Primaires (boost) : {", ".join(profile['geographies']['primary'])}
  - Secondaires : {", ".join(profile['geographies']['secondary'])}
  - Europe : selon synergie de co-investissement
- **Pas de restriction de ticket**

**Véhicules actuellement portés par UGFS :**
{vehicle_lines}

**Partenaires/co-investisseurs prioritaires :**
{partners_flat}

**Critères de DISQUALIFICATION immédiate :**
{dq_rules}

Ton rôle : pour chaque opportunité (appel d'offres, fund of funds, grant, RFP, etc.) que je te transmets,
tu produis une analyse structurée en **JSON STRICT** au format demandé. Tu ne réponds QUE le JSON,
sans markdown, sans préface, sans suffixe.

Tu es exigeant : si l'opportunité ne matche clairement aucun critère UGFS, tu mets `preliminary_decision: "NO_GO"`.
Si elle matche un véhicule actif (TGF, Blue Bond, Seed of Change, NEW ERA), tu mets `preliminary_decision: "GO"`.
Sinon tu utilises `BORDERLINE` ou `PENDING`.
"""


def _build_user_prompt(raw: RawOpportunity) -> str:
    """Prompt utilisateur : l'opportunité + le format de sortie attendu."""
    today = date.today().isoformat()

    schema_block = """{
  "title": "string (titre normalisé)",
  "summary_executive": "string (3-4 phrases en français, ce que c'est, qui le porte, pour qui)",
  "opportunity_type": "asset_management" | "grant" | "advisory" | "mandate" | "unknown",
  "theme": "green" | "blue" | "generaliste" | "unknown",
  "geographies": ["liste des pays/régions cibles"],
  "sectors": ["secteurs spécifiques: énergie, agriculture, santé, etc."],
  "eligibility_summary": "string (qui peut postuler, conditions clés)",
  "deadline": "YYYY-MM-DD ou null si rolling/non précisée",
  "deadline_text_raw": "texte brut original",
  "ticket_size_usd": null ou nombre entier (si mentionné, en USD),
  "languages": ["fr","en","ar",...],
  "why_interesting": "string (2-3 raisons concrètes pour UGFS)",
  "preliminary_decision": "GO" | "NO_GO" | "BORDERLINE" | "PENDING",
  "decision_rationale": "string (1-2 phrases sur le pourquoi de la reco)",
  "partners_mentioned": ["noms d'institutions/partenaires connus mentionnés"],
  "vehicle_match": "TGF" | "BLUE_BOND" | "SEED_OF_CHANGE" | "NEW_ERA" | null,
  "submission_url": "URL directe vers le formulaire de soumission ou null"
}"""

    return f"""Analyse cette opportunité (date d'aujourd'hui : {today}) et retourne le JSON conforme au schéma ci-dessous.

# Opportunité

**Titre :** {raw.title}

**URL :** {raw.url}

**Source :** {raw.source}

**Texte récupéré :**
\"\"\"
{raw.raw_text[:4000]}
\"\"\"

**Hint deadline (si fourni) :** {raw.deadline_hint or "rien"}

# Schéma JSON attendu (STRICT)

{schema_block}

Réponds uniquement avec le JSON valide, rien d'autre.
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


async def _call_llm(messages: list[dict], temperature: float = 0.1) -> str:
    """Appel LLM avec retry."""
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
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or "{}"
    return "{}"


# ============================================================
# API publique
# ============================================================

async def analyze_opportunity(raw: RawOpportunity) -> AnalyzedOpportunity | None:
    """
    Analyse une opportunité brute via le LLM.

    Retourne un AnalyzedOpportunity validé, ou None si l'analyse a échoué.
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
        logger.warning("llm_json_invalid", title=raw.title[:60], error=str(exc), raw=raw_json[:200])
        return None

    # Coerce certains types (le LLM peut renvoyer des null/strings au lieu d'enums)
    data = _coerce(data)

    try:
        analyzed = AnalyzedOpportunity(**data)
    except ValidationError as exc:
        logger.warning("llm_pydantic_invalid", title=raw.title[:60], errors=exc.errors()[:3])
        return None

    return analyzed


def _coerce(data: dict) -> dict:
    """Petits fix pour rendre la sortie LLM tolérante."""
    # Enums: si la valeur n'est pas dans l'enum, mettre "unknown" / "PENDING"
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

    # Listes: si le LLM renvoie une string, on en fait une liste à 1 élément
    for key in ("geographies", "sectors", "languages", "partners_mentioned"):
        v = data.get(key)
        if isinstance(v, str):
            data[key] = [s.strip() for s in v.split(",") if s.strip()]
        elif v is None:
            data[key] = []

    # ticket_size_usd: parser si string
    ticket = data.get("ticket_size_usd")
    if isinstance(ticket, str):
        digits = "".join(c for c in ticket if c.isdigit())
        data["ticket_size_usd"] = int(digits) if digits else None

    # Vehicle match: normaliser
    vm = data.get("vehicle_match")
    if vm and vm.upper() not in {"TGF", "BLUE_BOND", "SEED_OF_CHANGE", "NEW_ERA"}:
        data["vehicle_match"] = None
    elif vm:
        data["vehicle_match"] = vm.upper()

    return data
