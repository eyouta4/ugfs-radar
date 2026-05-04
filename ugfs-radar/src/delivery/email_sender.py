"""
src/delivery/email_sender.py — Envoi de l'email hebdo via Resend.

Pourquoi Resend ?
-----------------
- 3000 emails / mois gratuits (UGFS en utilisera ~5/mois)
- API REST simple, pas d'OAuth
- Webhooks pour bounces / replies (utile pour ingest_feedback)
- Domaine custom (radar@ugfs-na.com) avec DKIM/SPF facile à configurer

Format de l'email
-----------------
- Sujet : « UGFS-Radar · Édition du DD/MM/YYYY · N opportunités · M urgentes »
- Corps HTML responsive (cabinet conseil look)
- Pièce jointe : fichier .xlsx généré par excel_builder
- Top 3 opportunités citées dans le body pour donner un teaser
"""
from __future__ import annotations

import base64
from datetime import date
from typing import Sequence

import httpx

from src.config.logger import get_logger
from src.config.settings import get_settings
from src.storage.models import Opportunity

logger = get_logger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def _build_html_body(
    opportunities: Sequence[Opportunity],
    run_date: date,
) -> str:
    total = len(opportunities)
    qualified = sum(1 for o in opportunities if (o.score or 0) >= 50)
    high = sum(1 for o in opportunities if (o.score or 0) >= 70)
    urgent = sum(1 for o in opportunities if o.is_urgent)

    top3 = sorted(opportunities, key=lambda o: o.score or 0, reverse=True)[:3]

    top3_html = ""
    for i, opp in enumerate(top3, start=1):
        deadline_str = (
            opp.deadline.strftime("%d/%m/%Y")
            if opp.deadline else (opp.deadline_text_raw or "Rolling")
        )
        score_color = (
            "#16a34a" if (opp.score or 0) >= 70
            else "#ca8a04" if (opp.score or 0) >= 50
            else "#dc2626"
        )
        top3_html += f"""
        <tr>
          <td style="padding:12px 8px;border-bottom:1px solid #e5e7eb;width:40px;
                     font-weight:700;color:#0f2a4a;font-size:18px;">#{i}</td>
          <td style="padding:12px 8px;border-bottom:1px solid #e5e7eb;width:60px;
                     font-weight:700;color:{score_color};font-size:18px;">{opp.score}</td>
          <td style="padding:12px 8px;border-bottom:1px solid #e5e7eb;">
            <div style="font-weight:600;color:#0f2a4a;font-size:14px;">{opp.title}</div>
            <div style="color:#6b7280;font-size:12px;margin-top:4px;">
              {opp.opportunity_type or "—"} · {", ".join(opp.geographies or [])[:60] or "—"}
              · ⏱ {deadline_str}
            </div>
          </td>
        </tr>
        """

    urgent_banner = ""
    if urgent > 0:
        urgent_banner = f"""
        <div style="background:#fef2f2;border-left:4px solid #dc2626;padding:14px 18px;
                    margin:20px 0;border-radius:6px;">
          <div style="font-weight:700;color:#991b1b;font-size:14px;">
            ⚠️ {urgent} opportunité{"s" if urgent > 1 else ""} URGENTE{"S" if urgent > 1 else ""}
            (deadline ≤ 7 jours)
          </div>
          <div style="color:#7f1d1d;font-size:13px;margin-top:4px;">
            À traiter en priorité — voir l'onglet « Toutes opportunités » du fichier joint.
          </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:30px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.07);">
        <!-- Header -->
        <tr>
          <td style="background:#0f2a4a;padding:32px 40px;color:#ffffff;">
            <div style="font-size:13px;letter-spacing:1px;opacity:0.7;">UGFS-RADAR</div>
            <div style="font-size:24px;font-weight:700;margin-top:4px;">
              Veille hebdomadaire
            </div>
            <div style="font-size:14px;opacity:0.85;margin-top:8px;">
              Édition du {run_date.strftime('%d/%m/%Y')}
            </div>
          </td>
        </tr>

        <!-- Body -->
        <tr><td style="padding:32px 40px;">
          <p style="margin:0 0 18px 0;color:#1f2937;font-size:15px;line-height:1.55;">
            Bonjour,
          </p>
          <p style="margin:0 0 18px 0;color:#1f2937;font-size:15px;line-height:1.55;">
            Voici la synthèse hebdomadaire de la veille automatisée UGFS-Radar.
            <strong>{total}</strong> opportunités ont été détectées cette semaine,
            dont <strong>{qualified}</strong> qualifiées (score ≥ 50)
            et <strong>{high}</strong> prioritaires (score ≥ 70).
          </p>

          {urgent_banner}

          <h3 style="color:#0f2a4a;font-size:16px;margin:24px 0 12px 0;">
            🏆 Top 3 opportunités
          </h3>
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border-collapse:collapse;border-top:2px solid #0f2a4a;">
            {top3_html}
          </table>

          <p style="margin:24px 0 18px 0;color:#1f2937;font-size:15px;line-height:1.55;">
            Le détail complet est dans le fichier Excel joint :
          </p>
          <ul style="color:#374151;font-size:14px;line-height:1.8;">
            <li><strong>Onglet 1</strong> · Dashboard synthèse</li>
            <li><strong>Onglet 2</strong> · Toutes les opportunités triées par score</li>
            <li><strong>Onglet 3</strong> · Fiches détaillées par opportunité</li>
            <li><strong>Onglet 4</strong> · Comparaison avec l'historique UGFS</li>
          </ul>

          <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:14px 18px;
                      margin:24px 0;border-radius:6px;">
            <div style="font-weight:700;color:#15803d;font-size:14px;">📌 Boucle d'apprentissage</div>
            <div style="color:#166534;font-size:13px;margin-top:6px;line-height:1.5;">
              Après votre réunion interne, indiquez vos décisions
              <em>Go / No-Go</em> dans la colonne « Décision interne »
              de l'onglet 2 et renvoyez ce fichier à
              <strong>radar-feedback@ugfs-na.com</strong>.
              L'agent ajustera automatiquement ses critères de scoring.
            </div>
          </div>

          <p style="margin:24px 0 0 0;color:#6b7280;font-size:13px;line-height:1.5;">
            UGFS-Radar — agent autonome de veille stratégique.
          </p>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f9fafb;padding:16px 40px;border-top:1px solid #e5e7eb;
                       color:#6b7280;font-size:11px;text-align:center;">
          Email automatique · Pour toute question technique, contacter l'équipe IT.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _build_subject(opportunities: Sequence[Opportunity], run_date: date) -> str:
    total = len(opportunities)
    urgent = sum(1 for o in opportunities if o.is_urgent)
    base = f"UGFS-Radar · Édition du {run_date.strftime('%d/%m/%Y')} · {total} opportunités"
    if urgent > 0:
        return f"{base} · ⚠️ {urgent} urgente{'s' if urgent > 1 else ''}"
    return base


async def send_urgent_deadline_email(
    opportunities: Sequence[Opportunity],
    run_date: date | None = None,
) -> dict:
    """
    Envoie une alerte email pour les opportunités avec deadline ≤ 7 jours.

    Distinct du rapport hebdo : email ciblé, objet urgent, envoyé par le check quotidien.
    """
    settings = get_settings()
    if run_date is None:
        run_date = date.today()

    if not settings.resend_api_key:
        logger.warning("resend_api_key_missing — urgent email skipped")
        return {"skipped": True, "reason": "no_api_key"}

    if not settings.email_recipients:
        logger.warning("no_email_recipients — urgent email skipped")
        return {"skipped": True, "reason": "no_recipients"}

    n = len(opportunities)
    subject = f"⚠️ UGFS-Radar · {n} AO URGENT{'S' if n > 1 else ''} — deadline ≤ 7 jours ({run_date.strftime('%d/%m/%Y')})"

    rows_html = ""
    for opp in sorted(opportunities, key=lambda o: o.deadline or date.max):
        days = (opp.deadline - run_date).days if opp.deadline else None
        days_str = f"{days}j" if days is not None else "Rolling"
        color = "#dc2626" if (days is not None and days <= 3) else "#ca8a04"
        url = opp.url or ""
        title_link = f'<a href="{url}" style="color:#0f2a4a;">{opp.title}</a>' if url.startswith("http") else opp.title
        rows_html += f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #fecaca;font-weight:700;
                     color:{color};font-size:16px;width:50px;">{days_str}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #fecaca;">
            <div style="font-weight:600;font-size:14px;">{title_link}</div>
            <div style="color:#6b7280;font-size:12px;margin-top:3px;">
              Score : {opp.score}/100 · {opp.vehicle_match or opp.opportunity_type or '—'}
              · Deadline : {opp.deadline.strftime('%d/%m/%Y') if opp.deadline else 'Rolling'}
            </div>
          </td>
        </tr>
        """

    html_body = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#fef2f2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef2f2;padding:30px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:8px;overflow:hidden;border:2px solid #dc2626;">
        <tr>
          <td style="background:#dc2626;padding:24px 32px;color:#fff;">
            <div style="font-size:11px;letter-spacing:1px;opacity:0.8;">UGFS-RADAR · ALERTE DEADLINE</div>
            <div style="font-size:22px;font-weight:700;margin-top:4px;">
              ⚠️ {n} opportunité{'s' if n > 1 else ''} — deadline ≤ 7 jours
            </div>
            <div style="font-size:13px;opacity:0.85;margin-top:6px;">{run_date.strftime('%d/%m/%Y')}</div>
          </td>
        </tr>
        <tr><td style="padding:24px 32px;">
          <p style="margin:0 0 16px 0;color:#1f2937;font-size:15px;">
            Les opportunités ci-dessous requièrent une action <strong>immédiate</strong> d'UGFS.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border-collapse:collapse;border-top:2px solid #dc2626;">
            {rows_html}
          </table>
          <p style="margin:20px 0 0 0;color:#6b7280;font-size:13px;line-height:1.5;">
            Consultez le rapport hebdo complet dans votre boîte mail ou sur le dashboard UGFS-Radar.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    payload = {
        "from": settings.email_from,
        "to": settings.email_recipients,
        "subject": subject,
        "html": html_body,
    }
    if settings.email_cc_list:
        payload["cc"] = settings.email_cc_list

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            logger.info("urgent_deadline_email_sent", resend_id=data.get("id"), n_urgent=n)
            return data
        except httpx.HTTPStatusError as e:
            logger.error("resend_urgent_http_error", status=e.response.status_code,
                         body=e.response.text[:300])
            raise


async def send_weekly_email(
    opportunities: Sequence[Opportunity],
    excel_bytes: bytes,
    run_date: date | None = None,
) -> dict:
    """
    Envoie l'email hebdo avec le fichier Excel en pièce jointe.

    Returns:
        Réponse Resend ou {} si pas de clé API (mode dev).
    """
    settings = get_settings()
    if run_date is None:
        run_date = date.today()

    if not settings.resend_api_key:
        logger.warning("resend_api_key_missing — email skipped (dev mode)")
        return {"skipped": True, "reason": "no_api_key"}

    if not settings.email_recipients:
        logger.warning("no_email_recipients — email skipped")
        return {"skipped": True, "reason": "no_recipients"}

    subject = _build_subject(opportunities, run_date)
    html_body = _build_html_body(opportunities, run_date)
    filename = f"UGFS-Radar_{run_date.strftime('%Y-%m-%d')}.xlsx"

    payload = {
        "from": settings.email_from,
        "to": settings.email_recipients,
        "subject": subject,
        "html": html_body,
        "attachments": [
            {
                "filename": filename,
                "content": base64.b64encode(excel_bytes).decode("ascii"),
            }
        ],
    }
    if settings.email_cc_list:
        payload["cc"] = settings.email_cc_list

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            logger.info(
                "weekly_email_sent",
                resend_id=data.get("id"),
                recipients=len(settings.email_recipients),
                attachment_kb=round(len(excel_bytes) / 1024, 1),
            )
            return data
        except httpx.HTTPStatusError as e:
            logger.error(
                "resend_http_error",
                status=e.response.status_code,
                body=e.response.text[:500],
            )
            raise
