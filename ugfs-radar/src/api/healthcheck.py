"""src/api/healthcheck.py — endpoint /health avec état du dernier run."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select, text

from src.config.logger import get_logger
from src.storage.database import session_scope

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check() -> dict:
    """Status global de l'agent — utilisé par Railway + GitHub Actions."""
    db_ok    = False
    db_msg   = ""
    last_run = None

    try:
        async with session_scope() as session:
            r = await session.execute(text("SELECT 1"))
            db_ok  = r.scalar() == 1
            db_msg = "ok"

            # Dernier run réussi
            from src.storage.models import Run
            stmt = (
                select(Run)
                .where(Run.status == "OK")
                .order_by(Run.finished_at.desc())
                .limit(1)
            )
            run = (await session.execute(stmt)).scalar_one_or_none()
            if run:
                last_run = {
                    "id": run.id,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "status": run.status,
                    "new_opportunities": run.new_opportunities,
                    "urgent_alerts": run.urgent_alerts,
                }

    except Exception as e:
        db_msg = str(e)[:200]

    return {
        "status": "healthy" if db_ok else "degraded",
        "checks": {
            "database": {"ok": db_ok, "msg": db_msg},
        },
        "last_run": last_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
