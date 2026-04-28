"""
src/api/main.py — Service FastAPI (santé + feedback + dashboard web).

Le service expose :
  GET  /                     → dashboard web (login requis)
  GET  /login                → page de connexion
  POST /login                → traitement formulaire
  POST /logout               → déconnexion
  GET  /dashboard            → tableau de bord opérationnel
  GET  /opportunity/{id}     → fiche détaillée
  GET  /admin/users          → gestion utilisateurs (admin)
  GET  /admin/runs           → historique exécutions (admin)
  POST /api/decision         → décision Go/No-Go (1 clic)
  POST /api/upload-excel     → upload Excel renvoyé
  GET  /health               → status agent + DB
  POST /api/feedback/excel   → ingestion via API token (alternative)
  POST /api/feedback/single  → décision unitaire via API

Sécurité :
  - Auth bcrypt + JWT cookie httpOnly
  - Headers HSTS, CSP, X-Frame-Options, Referrer-Policy
  - Rate limiting login (5/15min/IP)
  - Audit log complet en DB
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.feedback import router as feedback_router
from src.api.healthcheck import router as health_router
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.storage.database import init_db
from src.web import web_router

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Ajoute les headers de sécurité standards à toutes les réponses."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS en prod uniquement
        if get_settings().environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP : ressources locales uniquement, scripts inline OK (pas de CDN externe)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "form-action 'self'; "
            "frame-ancestors 'none';"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_startup", environment=get_settings().environment)
    try:
        await init_db()
    except Exception as e:
        logger.error("db_init_failed", error=str(e))
    yield
    logger.info("api_shutdown")


app = FastAPI(
    title="UGFS-Radar",
    description="Veille stratégique automatisée — Dashboard sécurisé + API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(SecurityHeadersMiddleware)

# Routes web (priorité — ce sont les pages publiques)
app.include_router(web_router, tags=["web"])

# API technique
app.include_router(health_router, tags=["health"])
app.include_router(feedback_router, tags=["feedback-api"], prefix="/api/feedback")
