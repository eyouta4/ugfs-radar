"""
scripts/scheduler.py — Démarre le scheduler APScheduler en daemon.

Ce process tourne en permanence sur Railway (worker service) et déclenche :
  - Lundi 07h00 (Africa/Tunis) → run_weekly.main()
  - Tous les jours 08h00 → check des urgents (Teams alert si nouvelle deadline ≤ 7j)
  - Mensuel 1er du mois → scripts/recalibrate_weights.py

En dev local on peut le lancer avec `python -m scripts.scheduler`.
Sur Railway, ce script est l'entrypoint du service "worker" (cf railway.toml).
"""
from __future__ import annotations

import asyncio
import signal
from datetime import date

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
            # Alerte Teams
            try:
                teams_results = await send_urgent_alerts(urgent_list)
                logger.info("daily_urgent_teams_sent", n=len(teams_results))
            except Exception as e:
                logger.warning("daily_urgent_teams_failed", error=str(e))
            # Email deadline 7 jours
            try:
                await send_urgent_deadline_email(urgent_list)
                logger.info("daily_urgent_email_sent", n=len(urgent_list))
            except Exception as e:
                logger.warning("daily_urgent_email_failed", error=str(e))
        else:
            logger.info("daily_urgent_check_no_urgents")
    except Exception as e:
        logger.exception("daily_urgent_check_failed", error=str(e))


async def monthly_recalibrate():
    from scripts.recalibrate_weights import main as recal
    try:
        await recal()
    except Exception as e:
        logger.exception("scheduler_recalibrate_failed", error=str(e))


async def main():
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    # Run hebdo
    scheduler.add_job(
        weekly_job,
        CronTrigger(
            day_of_week=settings.weekly_run_day,
            hour=settings.weekly_run_hour,
            minute=settings.weekly_run_minute,
        ),
        id="weekly_run",
        replace_existing=True,
    )

    # Check urgents quotidien
    scheduler.add_job(
        daily_urgent_check,
        CronTrigger(hour=8, minute=0),
        id="daily_urgent_check",
        replace_existing=True,
    )

    # Recalibration mensuelle
    scheduler.add_job(
        monthly_recalibrate,
        CronTrigger(day=1, hour=3, minute=0),
        id="monthly_recalibrate",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        timezone=settings.timezone,
        weekly=f"{settings.weekly_run_day} {settings.weekly_run_hour}:{settings.weekly_run_minute:02d}",
    )

    # Bloque le process
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows
            pass
    await stop.wait()
    scheduler.shutdown(wait=False)
    logger.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
