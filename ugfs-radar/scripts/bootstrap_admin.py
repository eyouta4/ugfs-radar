"""
scripts/bootstrap_admin.py — Crée le premier utilisateur admin.

À exécuter UNE FOIS au déploiement initial pour pouvoir se connecter
au dashboard web. Ensuite, l'admin créé peut créer les autres comptes
via /admin/users.

Usage :
    python -m scripts.bootstrap_admin                  # interactif
    python -m scripts.bootstrap_admin --email a@b.com --password "..." --name "Alice"
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

try:
    from sqlalchemy import select
except ImportError as exc:
    raise SystemExit(
        "❌ SQLAlchemy n'est pas installé. Installez les dépendances avec `pip install -r requirements.txt` "
        "puis réessayez."
    ) from exc

# Fixe le chemin d'import quand le script est exécuté depuis un répertoire parent.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.logger import get_logger
from src.storage.database import init_db, session_scope
from src.storage.models import User
from src.web.auth import hash_password

logger = get_logger(__name__)


async def main(email: str, full_name: str, password: str) -> None:
    if len(password) < 12:
        print("❌ Mot de passe : 12 caractères minimum.")
        sys.exit(1)

    await init_db()

    async with session_scope() as session:
        existing = (await session.execute(
            select(User).where(User.email == email.lower().strip())
        )).scalar_one_or_none()
        if existing:
            print(f"⚠️  Un utilisateur avec l'email {email} existe déjà.")
            update = input("Réinitialiser son mot de passe ? (yes/no): ").strip().lower()
            if update == "yes":
                existing.password_hash = hash_password(password)
                existing.is_active = True
                existing.role = "admin"
                print(f"✓ Mot de passe réinitialisé pour {email}.")
            else:
                print("Annulé.")
            return

        user = User(
            email=email.lower().strip(),
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.flush()

    print(f"✓ Admin créé : {email}")
    print(f"   Connexion : https://votre-app.up.railway.app/login")


def cli():
    p = argparse.ArgumentParser(description="Crée le premier admin du dashboard.")
    p.add_argument("--email", help="Adresse email")
    p.add_argument("--name", help="Nom complet")
    p.add_argument("--password", help="Mot de passe (≥12 car.)")
    args = p.parse_args()

    email = args.email or input("Email admin : ").strip()
    full_name = args.name or input("Nom complet : ").strip()
    password = args.password or getpass.getpass("Mot de passe (≥12 car.) : ")

    asyncio.run(main(email, full_name, password))


if __name__ == "__main__":
    cli()
