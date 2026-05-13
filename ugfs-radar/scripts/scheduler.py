"""
scripts/scheduler.py — Daemon APScheduler (worker Railway).

Déclenchements :
  - Mercredi 20h00 (Africa/Tunis) → run_weekly.main()        ← PRIORITAIRE
  - Dimanche 18h00                → run_weekly.main() si pas encore fait cette semaine (failsafe)
  - Tous les jours 08h00          → check deadlines urgentes (Teams + email)
  - Jeudi 09h00                   → alerte deadline J-7 pour toutes AOs avec deadline la semaine suivante
  - Mensuel 1er du mois 03h00     → recalibration des poids ML

Architecture de fiabilité :
  1. GitHub Actions (principal)    → POST /api/feedback/trigger-weekly
  2. APScheduler worker (fallback) → run_weekly directement si Actions échoue
  3. Le dimanche est un 2e filet : si mercredi ET GitHub Actions ont tous deux échoué,
     le run se déclenche dimanche avec les AOs de la semaine entière.
"""
from __future__ import annotations

import asyncio
import signal
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)


async def weekly_job():
    from scripts.run_weekly import main as run_weekly
    try:
        result = await run_weekly()
        logger.info("scheduler_weekly_ok", **result)
    except Exception as e:
        logger.exception("scheduler_weekly_failed", error=str(e))


async def sunday_failsafe_job():
    """
    Filet de sécurité dimanche 18h00 : déclenche le run si aucune exécution
    réussie n'a eu lieu mercredi, jeudi ou vendredi de cette semaine.
    """
    from src.storage.database import init_db, session_scope
    from src.storage.models import Run
    from sqlalchemy import select

    await init_db()
    today = date.today()
    wednesday = today - timedelta(days=(today.weekday() - 2) % 7)   # mercredi de cette semaine

    async with session_scope() as session:
        stmt = (
            select(Run)
            .where(Run.started_at >= wednesday.isoformat())
            .where(Run.status == "OK")
        )
        result = await session.execute(stmt)
        runs_this_week = result.scalars().all()

    if not runs_this_week:
        logger.warning("sunday_failsafe_triggered — aucun run OK cette semaine, lancement forcé")
        await weekly_job()
    else:
        logger.info("sunday_failsafe_skip — run OK déjà effectué cette semaine",
                    n_runs=len(runs_this_week))


async def daily_urgent_check():
    """Vérifie quotidiennement les urgents et envoie alertes Teams + email deadline."""
    from src.delivery import send_urgent_alerts
    from src.delivery.email_sender import send_urgent_deadline_email
    from src.storage.database import session_scope
    from src.storage.repository import OpportunityRepo
    try:
        async with session_scope() as session:
            repo = OpportunityRepo(session)
            urgent = await repo.list_urgent_unprocessed()
        if urgent:
            urgent_list = list(urgent)
            try:
                teams_results = await send_urgent_alerts(urgent_list)
                logger.info("daily_urgent_teams_sent", n=len(teams_results))
            except Exception as e:
                logger.warning("daily_urgent_teams_failed", error=str(e))
            try:
                await send_urgent_deadline_email(urgent_list)
                logger.info("daily_urgent_email_sent", n=len(urgent_list))
            except Exception as e:
                logger.warning("daily_urgent_email_failed", error=str(e))
        else:
            logger.info("daily_urgent_check_no_urgents")
    except Exception as e:
        logger.exception("daily_urgent_check_failed", error=str(e))


async def thursday_deadline_alert():
    """
    Chaque jeudi 09h00 : identifie les AOs dont la deadline est la semaine suivante
    (J+7 à J+14) et envoie un email d'alerte si UGFS n'a pas encore décidé.
    Garantit que l'équipe ne rate pas une deadline même si elle n'a pas lu l'email lundi.
    """
    from datetime import timedelta
    from src.delivery.email_sender import send_urgent_deadline_email
    from src.storage.database import session_scope
    from src.storage.repository import OpportunityRepo

    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    next_friday  = next_monday + timedelta(days=4)

    try:
        async with session_scope() as session:
            from sqlalchemy import select
            from src.storage.models import Opportunity
            stmt = (
                select(Opportunity)
                .where(Opportunity.deadline >= next_monday)
                .where(Opportunity.deadline <= next_friday)
                .where(Opportunity.client_decision.is_(None))
                .where(Opportunity.score >= 40)
                .order_by(Opportunity.deadline.asc())
            )
            result = await session.execute(stmt)
            upcoming = result.scalars().all()

        if upcoming:
            logger.info("thursday_deadline_alert", n=len(upcoming))
            await send_urgent_deadline_email(list(upcoming), run_date=today)
        else:
            logger.info("thursday_no_upcoming_deadlines")
    except Exception as e:
        logger.exception("thursday_deadline_alert_failed", error=str(e))


async def monthly_recalibrate():
    from scripts.recalibrate_weights import main as recal
    try:
        await recal()
    except Exception as e:
        logger.exception("scheduler_recalibrate_failed", error=str(e))


async def main():
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    # ── Run hebdo principal (lundi) ─────────────────────────────────────
    scheduler.add_job(
        weekly_job,
        CronTrigger(
            day_of_week=settings.weekly_run_day,   # "mon"
            hour=settings.weekly_run_hour,          # 7
            minute=settings.weekly_run_minute,      # 0
            timezone=settings.timezone,
        ),
        id="weekly_run",
        replace_existing=True,
        misfire_grace_time=3600,   # tolérance 1h si Railway redémarre au mauvais moment
    )

    # ── Filet de sécurité dimanche ──────────────────────────────────────
    scheduler.add_job(
        sunday_failsafe_job,
        CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=settings.timezone),
        id="sunday_failsafe",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── Check urgents quotidien 08h00 ────────────────────────────────────
    scheduler.add_job(
        daily_urgent_check,
        CronTrigger(hour=8, minute=0, timezone=settings.timezone),
        id="daily_urgent_check",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # ── Alerte deadline J-7 chaque jeudi 09h00 ──────────────────────────
    scheduler.add_job(
        thursday_deadline_alert,
        CronTrigger(day_of_week="thu", hour=9, minute=0, timezone=settings.timezone),
        id="thursday_deadline_alert",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Recalibration mensuelle 1er du mois 03h00 ────────────────────────
    scheduler.add_job(
        monthly_recalibrate,
        CronTrigger(day=1, hour=3, minute=0, timezone=settings.timezone),
        id="monthly_recalibrate",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        timezone=settings.timezone,
        weekly=f"{settings.weekly_run_day} {settings.weekly_run_hour}:{settings.weekly_run_minute:02d}",
        failsafe="sunday 18:00",
        daily_urgent="08:00",
        thursday_alert="09:00",
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass   # Windows
    await stop.wait()
    scheduler.shutdown(wait=False)
    logger.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
