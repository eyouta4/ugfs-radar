"""
src/delivery/teams_alerter.py — Alerte temps réel Microsoft Teams.

Authentification : OAuth 2.0 client credentials (app-only)
  → tenant_id, client_id, client_secret enregistrés dans Azure AD
  → permissions Graph requises :
        ChannelMessage.Send         (poster dans un canal)
        Team.ReadBasic.All          (lire la liste des équipes)
        Channel.ReadBasic.All       (lire les canaux)
        Chat.Read.All               (lire les conversations privées si corpus)
        Files.Read.All              (lire fichiers partagés si corpus)

Voir docs/04_TEAMS_INTEGRATION.md pour le step-by-step admin Azure.

Stratégie d'alerte
------------------
- Une carte adaptive (Microsoft Adaptive Card) par opportunité urgente
- Couleur d'attention selon la criticité (rouge si ≤ 3j, orange si 4-7j)
- Lien direct vers la source + lien vers la fiche détaillée Excel
- Anti-spam : on ne re-poste pas une opportunité déjà alertée (statut tracking)
"""
from __future__ import annotations

import time
from datetime import date
from typing import Sequence

import httpx

from src.config.logger import get_logger
from src.config.settings import get_settings
from src.storage.models import Opportunity

logger = get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


# ============================================================
# OAuth (app-only)
# ============================================================

class GraphTokenManager:
    """Gestion du token OAuth client_credentials avec cache + auto-refresh."""

    def __init__(self):
        s = get_settings()
        self.tenant = s.teams_tenant_id
        self.client_id = s.teams_client_id
        self.client_secret = s.teams_client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def get(self, client: httpx.AsyncClient) -> str:
        """Retourne un token valide (renouvelle si nécessaire)."""
        # 60s de marge avant expiration
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        url = TOKEN_URL.format(tenant=self.tenant)
        resp = await client.post(
            url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        logger.debug("graph_token_acquired", expires_in=data.get("expires_in"))
        return self._token  # type: ignore[return-value]


# ============================================================
# Adaptive Cards
# ============================================================

def _criticity_color(opp: Opportunity) -> str:
    if not opp.deadline:
        return "default"
    days = (opp.deadline - date.today()).days
    if days <= 3:
        return "attention"  # rouge
    if days <= 7:
        return "warning"    # orange
    return "good"


def _build_adaptive_card(opp: Opportunity) -> dict:
    deadline_str = (
        opp.deadline.strftime("%d/%m/%Y") if opp.deadline else "Rolling"
    )
    days_left = (opp.deadline - date.today()).days if opp.deadline else None
    days_str = f"⏱ {days_left} jour(s)" if days_left is not None else ""

    facts = [
        {"title": "Score", "value": f"{opp.score}/100"},
        {"title": "Type", "value": opp.opportunity_type or "—"},
        {"title": "Géographies", "value": ", ".join(opp.geographies or []) or "—"},
        {"title": "Deadline", "value": f"{deadline_str} {days_str}"},
    ]
    if opp.vehicle_match:
        facts.append({"title": "Véhicule UGFS", "value": opp.vehicle_match})
    if opp.partners_mentioned:
        facts.append(
            {"title": "Partenaires", "value": ", ".join(opp.partners_mentioned[:3])}
        )

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "🚨 OPPORTUNITÉ URGENTE",
                "weight": "Bolder",
                "color": _criticity_color(opp),
                "size": "Small",
                "spacing": "None",
            },
            {
                "type": "TextBlock",
                "text": opp.title,
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "TextBlock",
                "text": (opp.summary_executive or "")[:280],
                "isSubtle": True,
                "wrap": True,
                "size": "Small",
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": facts,
                "spacing": "Medium",
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Voir la source",
                "url": opp.url,
            },
            *(
                [{
                    "type": "Action.OpenUrl",
                    "title": "Formulaire de soumission",
                    "url": opp.submission_url,
                }] if opp.submission_url else []
            ),
        ],
    }


# ============================================================
# API publique
# ============================================================

async def send_urgent_alerts(
    urgent_opportunities: Sequence[Opportunity],
) -> list[dict]:
    """
    Envoie une carte par opportunité urgente dans le canal Teams configuré.

    Returns:
        Liste des réponses Graph (1 par message envoyé).
    """
    settings = get_settings()

    if not settings.teams_enabled:
        logger.info("teams_disabled — alerts skipped")
        return []

    if not all([
        settings.teams_tenant_id, settings.teams_client_id,
        settings.teams_client_secret, settings.teams_team_id,
        settings.teams_channel_id,
    ]):
        logger.warning("teams_credentials_incomplete — alerts skipped")
        return []

    if not urgent_opportunities:
        logger.info("no_urgent_opportunities")
        return []

    token_manager = GraphTokenManager()
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await token_manager.get(client)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = (
            f"{GRAPH_API_BASE}/teams/{settings.teams_team_id}"
            f"/channels/{settings.teams_channel_id}/messages"
        )

        for opp in urgent_opportunities:
            card = _build_adaptive_card(opp)
            payload = {
                "subject": f"UGFS-Radar : {opp.title[:80]}",
                "body": {
                    "contentType": "html",
                    "content": (
                        '<attachment id="card1"></attachment>'
                    ),
                },
                "attachments": [
                    {
                        "id": "card1",
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card,
                    }
                ],
            }
            try:
                r = await client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                msg = r.json()
                logger.info(
                    "teams_alert_sent",
                    opp_id=opp.id,
                    title=opp.title[:60],
                    msg_id=msg.get("id"),
                )
                results.append(msg)
            except httpx.HTTPStatusError as e:
                logger.error(
                    "teams_alert_failed",
                    opp_id=opp.id,
                    status=e.response.status_code,
                    body=e.response.text[:300],
                )

    return results


# ============================================================
# Lecture du corpus Teams (Module 6 du cahier des charges)
# ============================================================

async def fetch_team_messages(
    team_id: str,
    channel_id: str,
    limit: int = 100,
) -> list[dict]:
    """
    Lit les N derniers messages d'un canal Teams (corpus de calibration).

    Cette fonction est utilisée par scripts/build_teams_corpus.py pour
    construire un corpus métier qu'on pourra ensuite vectoriser et utiliser
    comme contexte d'embedding (vocabulaire interne, priorités, décisions).
    """
    settings = get_settings()
    token_manager = GraphTokenManager()
    messages: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await token_manager.get(client)
        headers = {"Authorization": f"Bearer {token}"}
        url = (
            f"{GRAPH_API_BASE}/teams/{team_id}/channels/{channel_id}/messages"
            f"?$top={min(limit, 50)}"
        )
        while url and len(messages) < limit:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            messages.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

    logger.info("teams_messages_fetched", n=len(messages))
    return messages[:limit]
