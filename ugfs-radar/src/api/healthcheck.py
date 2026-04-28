"""src/api/healthcheck.py — endpoint /health."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from src.config.logger import get_logger
from src.storage.database import session_scope

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check() -> dict:
    """Status global de l'agent."""
    db_ok = False
    db_msg = ""
    try:
        async with session_scope() as session:
            r = await session.execute(text("SELECT 1"))
            db_ok = r.scalar() == 1
            db_msg = "ok"
    except Exception as e:
        db_msg = str(e)[:200]

    return {
        "status": "healthy" if db_ok else "degraded",
        "checks": {
            "database": {"ok": db_ok, "msg": db_msg},
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
