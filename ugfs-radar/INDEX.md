# UGFS-Radar — Sommaire de la livraison

> **Pour qui ?**
> 1. **Sponsor projet UGFS** : commencer par [`docs/EMAIL_TO_CLIENT.md`](docs/EMAIL_TO_CLIENT.md) puis [`docs/05_CLIENT_USER_GUIDE.md`](docs/05_CLIENT_USER_GUIDE.md)
> 2. **Direction** : [`README.md`](README.md) puis [`docs/06_ROADMAP.md`](docs/06_ROADMAP.md)
> 3. **Équipe IT** : [`docs/02_DEV_ENVIRONMENT.md`](docs/02_DEV_ENVIRONMENT.md), [`docs/03_API_KEYS_GUIDE.md`](docs/03_API_KEYS_GUIDE.md), [`docs/04_TEAMS_INTEGRATION.md`](docs/04_TEAMS_INTEGRATION.md)
> 4. **Architecte/dev** : [`docs/01_ARCHITECTURE.md`](docs/01_ARCHITECTURE.md) puis exploration du dossier `src/`

---

## Plan de la livraison

### 📚 Documentation (`docs/`)

| Fichier | Lecteur | Contenu |
|---------|---------|---------|
| `00_DATA_MISSING_FROM_CLIENT.md` | Sponsor UGFS | Données manquantes à fournir avant déploiement (poids, historique, accès Teams…) |
| `01_ARCHITECTURE.md` | Architecte / dev | Architecture technique complète, stack, sécurité, RGPD |
| `02_DEV_ENVIRONMENT.md` | Dev | Setup Codespaces + Railway en pas-à-pas |
| `03_API_KEYS_GUIDE.md` | Équipe IT | Obtention des 9 clés API (Groq, Voyage, Resend, Google, Sentry…) |
| `04_TEAMS_INTEGRATION.md` | Admin Microsoft 365 | Configuration Azure AD pour intégration Teams |
| `05_CLIENT_USER_GUIDE.md` | Équipe métier UGFS | Guide d'utilisation non-technique |
| `06_ROADMAP.md` | Sponsor / Direction | Vision d'évolution V1.0 → V3.0 |
| `EMAIL_TO_CLIENT.md` | À envoyer au client | Email type pour récupérer les inputs manquants |

### 🧠 Code source (`src/`)

| Module | Rôle |
|--------|------|
| `config/` | Settings Pydantic, schémas pipeline, logger structuré |
| `storage/` | Modèles SQLAlchemy (Postgres + pgvector), repositories, users + audit log |
| `collectors/` | 4 collecteurs async : Google CSE, EU Funding Portal, RSS, LinkedIn |
| `analyzer/` | LLM analyzer (Groq), embeddings (Voyage), similarité, scoring déterministe |
| `delivery/` | Builder Excel 4 onglets, sender email Resend, alerter Teams Adaptive Cards |
| `api/` | Service FastAPI : `/health`, `/api/feedback/excel`, `/api/feedback/single` |
| **`web/`** | **Dashboard web sécurisé : login bcrypt+JWT, décisions 1-clic, admin** |

### ⚙️ Scripts opérationnels (`scripts/`)

| Script | Quand l'utiliser |
|--------|------------------|
| `seed_historical.py` | Une fois au déploiement initial → charge le CSV des AO passés en DB |
| **`bootstrap_admin.py`** | **Une fois → crée le premier compte admin pour le dashboard web** |
| `run_weekly.py` | Manuel ou via scheduler → exécute le pipeline complet |
| `scheduler.py` | Tourne en daemon → déclenche `run_weekly` chaque lundi 7h |
| `ingest_feedback.py` | CLI pour ingérer manuellement un Excel modifié |
| `recalibrate_weights.py` | Recalibre les poids de scoring depuis les feedbacks accumulés |

### 🚀 Déploiement (`deploy/`)

- `Dockerfile` — image production
- `railway.toml` — config Railway (2 services : api + worker)
- `docker-compose.yml` — stack locale avec Postgres+pgvector

### 🤖 CI/CD (`.github/workflows/`)

- `ci.yml` — tests automatiques sur push
- `cron-backup.yml` — backup quotidien de la DB

### 📊 Données (`data/`)

- `ugfs_profile.yaml` — **source de vérité du scoring** (poids, véhicules, partenaires, règles DQ)
- `historical_ao.csv` — historique nettoyé des 42 opportunités passées d'UGFS

### 🧪 Tests (`tests/`)

33 tests unitaires couvrant scoring, fingerprint, Excel builder.

---

## Démarrage rapide (équipe technique)

```bash
# 1. Cloner le repo
git clone <url>/ugfs-radar.git && cd ugfs-radar

# 2. Configurer les clés API
cp .env.example .env
# Remplir .env selon docs/03_API_KEYS_GUIDE.md

# 3. Lancer en local (Docker)
docker compose -f deploy/docker-compose.yml up

# 4. Initialiser la DB avec l'historique
docker compose -f deploy/docker-compose.yml exec api python -m scripts.seed_historical

# 5. Tester un run hebdo manuel
docker compose -f deploy/docker-compose.yml exec api python -m scripts.run_weekly

# 6. Vérifier l'email reçu, le fichier Excel généré, et l'API
curl http://localhost:8000/health
```

---

## Démarrage rapide (sponsor UGFS)

1. **Lire** [`docs/EMAIL_TO_CLIENT.md`](docs/EMAIL_TO_CLIENT.md) — comprendre ce qui est demandé
2. **Compléter** les TO_CONFIRM dans [`data/ugfs_profile.yaml`](data/ugfs_profile.yaml)
3. **Valider** le périmètre des sources avec l'équipe technique
4. **Déléguer** la création des clés API à l'IT (voir [`docs/03_API_KEYS_GUIDE.md`](docs/03_API_KEYS_GUIDE.md))
5. **Recevoir** le premier email de test
6. **Itérer** : indiquer Go/No-Go dans l'Excel renvoyé chaque semaine pour que l'agent se calibre

---

## Statut de livraison

✅ **MVP V1.0 complet** — 4 collecteurs, analyzer LLM, scoring, Excel pro, email, Teams, API feedback, learning loop, déploiement, CI/CD, tests, documentation exhaustive.

📅 **Prochaine étape** : déploiement en environnement de test UGFS dès récupération des accès et clés API.
