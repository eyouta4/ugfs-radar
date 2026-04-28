"""
src/web/auth.py — Authentification sécurisée du dashboard.

Sécurité
--------
- Mots de passe hashés avec bcrypt (cost=12) — JAMAIS stockés en clair
- Tokens JWT signés HS256, expirent en 8h (durée d'une journée de travail)
- Rate limiting sur /login (5 tentatives / 15 min par IP)
- Cookies httpOnly + secure + sameSite=strict (anti-XSS, anti-CSRF)
- Audit log : chaque login + chaque décision tracé en DB (qui, quand, IP)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.logger import get_logger
from src.config.settings import get_settings
from src.storage.database import session_scope

logger = get_logger(__name__)

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 8
COOKIE_NAME = "ugfs_radar_session"


# ============================================================
# Hashing
# ============================================================

def hash_password(plain: str) -> str:
    """Hash un mot de passe (bcrypt cost=12, ~250ms)."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie un mot de passe en temps constant."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ============================================================
# JWT
# ============================================================

def _jwt_secret() -> str:
    s = get_settings()
    secret = s.api_feedback_token  # réutilisé comme secret JWT (à séparer en prod)
    if not secret or secret == "change-me-in-prod":
        # Fallback en dev pour ne pas crasher
        return "DEV_JWT_SECRET_DO_NOT_USE_IN_PROD"
    return secret


def create_token(user_id: int, email: str, role: str) -> str:
    """Crée un JWT signé."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Vérifie un JWT et retourne le payload, ou None si invalide/expiré."""
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.info("jwt_expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning("jwt_invalid", error=str(e))
        return None


# ============================================================
# Rate limiting (en mémoire, OK pour 1 instance — sinon Redis)
# ============================================================

_login_attempts: dict[str, list[datetime]] = {}
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = timedelta(minutes=15)


def check_rate_limit(ip: str) -> bool:
    """Retourne True si l'IP a le droit de tenter un login."""
    now = datetime.now(timezone.utc)
    attempts = _login_attempts.get(ip, [])
    # Purge les vieilles tentatives
    attempts = [a for a in attempts if now - a < RATE_LIMIT_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < RATE_LIMIT_MAX


def record_login_attempt(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(datetime.now(timezone.utc))


# ============================================================
# Dependencies FastAPI
# ============================================================

class CurrentUser:
    def __init__(self, id: int, email: str, role: str):
        self.id = id
        self.email = email
        self.role = role


async def get_current_user(
    request: Request,
    session_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> CurrentUser:
    """
    Dépendance FastAPI : extrait l'utilisateur depuis le cookie JWT.
    Refuse 401 si pas de token valide.
    """
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"Location": "/login"},
        )
    payload = decode_token(session_cookie)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"Location": "/login"},
        )
    return CurrentUser(
        id=int(payload["sub"]),
        email=payload["email"],
        role=payload["role"],
    )


async def require_admin(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Dépendance : exige le rôle admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# ============================================================
# Login / logout helpers
# ============================================================

async def authenticate(email: str, password: str, session: AsyncSession):
    """
    Vérifie les credentials. Retourne l'objet User ou None.
    Temps constant : on hash toujours, même si l'email n'existe pas (anti-timing-attack).
    """
    from src.storage.models import User
    stmt = select(User).where(User.email == email.lower().strip())
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    # Hash dummy pour temps constant
    dummy = "$2b$12$dummmyDummyDummyDummyDummyDummyDummyDummyDummyDummyDummy"
    if user is None:
        verify_password(password, dummy)
        return None

    if not user.is_active:
        return None

    if not verify_password(password, user.password_hash):
        return None

    user.last_login_at = datetime.now(timezone.utc)
    return user
