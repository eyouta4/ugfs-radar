# 02 — Environnement de développement & déploiement (sans machine puissante)

## 0. Le principe directeur

Vous codez et testez **dans le navigateur**. Tout ce qui s'exécute (Python, base de données, LLM, scraper) tourne sur des serveurs gérés par d'autres. Votre laptop n'a besoin que d'**un navigateur Chrome/Edge/Firefox**.

---

## 1. Stack de développement (gratuite)

| Outil | Rôle | Coût | Comment y accéder |
|---|---|---|---|
| **GitHub** | Stockage du code, issues, CI/CD | Gratuit (repo privé illimité) | https://github.com (créer un compte) |
| **GitHub Codespaces** | IDE complet dans le navigateur | Gratuit 60h/mois (150h/mois pour Pro à 4$/mois si besoin) | Ouvre depuis github.com/votre-repo → bouton vert "Code" → Codespaces |
| **Railway** | Hébergement + DB Postgres + cron | ~5€/mois | https://railway.app — connecter avec GitHub |
| **Groq Cloud** | LLM gratuit (Llama 3.3 70B) | Free tier | https://console.groq.com |
| **Voyage AI** | Embeddings gratuits | Free tier 200M tokens | https://www.voyageai.com |
| **Resend** | Envoi d'email | Free 3000/mois | https://resend.com |
| **Sentry** | Capture des erreurs | Free 5k events/mois | https://sentry.io |
| **UptimeRobot** | Monitoring uptime | Free 50 monitors | https://uptimerobot.com |

**Total à débourser : ~5€/mois (juste Railway).**

---

## 2. Pas-à-pas — création du projet

### Étape 2.1 — Créer un compte GitHub et un repo

1. https://github.com → "Sign up" (gratuit).
2. Créer un nouveau repo **privé** : nom `ugfs-radar`, description "AI agent for UGFS-NA AO sourcing", **NE PAS** ajouter README/license maintenant (on aura les nôtres).
3. Copier l'URL du repo (`https://github.com/<votre-user>/ugfs-radar`).

### Étape 2.2 — Pusher le code initial

Vous avez deux options selon votre confort :

**Option A — depuis la box Codespaces directement (recommandé, 5 min, zéro install local) :**

1. Sur le repo vide, cliquer "Code" → "Codespaces" → "Create codespace on main". Un IDE VSCode s'ouvre dans le navigateur (chargement ~30 sec).
2. Dans le terminal du Codespace, copier les fichiers fournis dans le livrable :
   ```bash
   # Le livrable ugfs-radar.zip contient toute la structure
   # Le décompresser dans le repo
   unzip /tmp/ugfs-radar.zip -d .
   git add .
   git commit -m "Initial commit: UGFS-Radar v1.0"
   git push
   ```

**Option B — depuis un terminal local (Mac/Linux/Windows avec Git installé) :**

1. Installer Git : https://git-scm.com/downloads (5 min).
2. Cloner le repo vide :
   ```bash
   git clone https://github.com/<votre-user>/ugfs-radar.git
   cd ugfs-radar
   ```
3. Décompresser le livrable dans le dossier, puis :
   ```bash
   git add .
   git commit -m "Initial commit: UGFS-Radar v1.0"
   git push
   ```

### Étape 2.3 — Ouvrir le projet dans Codespaces

1. Sur le repo GitHub, cliquer **Code** → onglet **Codespaces** → **Create codespace on main**.
2. Attendre ~1 minute que l'environnement se charge (Python 3.11, pip, postgres-client, etc.).
3. Le `devcontainer.json` (fourni dans le livrable) installe automatiquement les dépendances. Sinon, lancer manuellement :
   ```bash
   pip install -r requirements.txt
   ```
4. Configurer les secrets locaux pour les tests :
   ```bash
   cp .env.example .env
   # Ouvrir .env et coller les vraies clés API (Groq, Voyage, Resend...)
   ```

### Étape 2.4 — Récupérer les clés API

Chaque service a son propre flux d'inscription. Pas-à-pas dans `docs/03_API_KEYS_GUIDE.md`. Résumé :

| Service | Comment obtenir la clé |
|---|---|
| Groq | console.groq.com → API Keys → Create. Gratuit, ~30 sec. |
| Voyage AI | dashboard.voyageai.com → API Keys → Create. Gratuit, ~30 sec. |
| Resend | resend.com → API Keys → Create. Gratuit, ~30 sec. Domaine à vérifier après. |
| Google CSE (recherche web) | programmablesearchengine.google.com → créer un moteur "tout le web", récupérer le `cx`. Puis console.cloud.google.com → activer Custom Search API → créer une API key. |
| Sentry | sentry.io → créer une orga → projet Python → DSN à copier. |

### Étape 2.5 — Tester l'agent en local (dans le Codespace)

```bash
# Lancer la base Postgres locale (le devcontainer en a déjà une)
make db-up

# Initialiser le schéma + seed historique UGFS
python scripts/seed_historical.py

# Lancer un dry-run (scrape + score, pas d'email envoyé)
python scripts/run_weekly.py --dry-run --limit 10

# Vérifier le résultat
ls data/output/
# devrait contenir un fichier ugfs-radar-weekly-YYYY-MM-DD.xlsx

# Tests unitaires
pytest tests/ -v
```

---

## 3. Déploiement sur Railway

### Étape 3.1 — Créer le projet Railway

1. https://railway.app → "Login with GitHub".
2. "New Project" → "Deploy from GitHub repo" → choisir `ugfs-radar`.
3. Railway détecte le `Dockerfile` et le `railway.toml` fournis et configure tout seul.

### Étape 3.2 — Ajouter Postgres

1. Dans le projet Railway, cliquer "+ New" → "Database" → "PostgreSQL".
2. Une variable d'environnement `DATABASE_URL` est créée automatiquement et injectée dans le service.
3. Activer l'extension `pgvector` (depuis l'UI ou en SQL via le terminal Railway) :
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

### Étape 3.3 — Configurer les variables d'environnement

Dans l'UI Railway, onglet **Variables** du service, ajouter :

```
GROQ_API_KEY=gsk_...
VOYAGE_API_KEY=pa-...
RESEND_API_KEY=re_...
GOOGLE_CSE_API_KEY=AIza...
GOOGLE_CSE_ID=...
SENTRY_DSN=https://...@sentry.io/...
EMAIL_FROM=radar@ugfs-na.com
EMAIL_TO=ines@ugfs-na.com,lotfi@ugfs-na.com,...
TEAMS_TENANT_ID=...
TEAMS_CLIENT_ID=...
TEAMS_CLIENT_SECRET=...
TEAMS_CHANNEL_ID=...
TIMEZONE=Africa/Tunis
LOG_LEVEL=INFO
```

### Étape 3.4 — Activer le scheduler

Le `railway.toml` configure un service dédié qui exécute APScheduler. Au déploiement Railway lance le service en mode démon ; le cron lundi 7h Tunis se déclenche tout seul.

### Étape 3.5 — Initialiser la DB en production

Une seule fois après le premier déploiement :

```bash
# Depuis le Codespace, avec le CLI Railway connecté
railway link
railway run python scripts/seed_historical.py
```

### Étape 3.6 — Tester un run manuel en prod (sans attendre lundi)

```bash
railway run python scripts/run_weekly.py
```

Si tout est bon, l'équipe UGFS reçoit l'Excel par email.

---

## 4. Workflow de développement quotidien

```
1. Ouvrir Codespace → l'env est déjà prêt
2. Créer une branche : git checkout -b feature/add-bei-collector
3. Coder + tester en local : pytest tests/collectors/test_bei.py
4. Push : git push -u origin feature/add-bei-collector
5. Ouvrir une PR sur GitHub → GitHub Actions lance pytest
6. Merger → Railway déploie automatiquement
7. Vérifier les logs Railway pour s'assurer que le déploiement passe
```

---

## 5. Tester l'agent sans machine puissante — récap

- **Pas de Docker local** nécessaire (le Codespace fournit Docker).
- **Pas de Postgres local** nécessaire (le Codespace en lance un dans son container).
- **Pas de scraping local** : tous les tests réseau utilisent les fixtures VCR enregistrées (rejouables offline).
- **Pas d'envoi d'email réel en dev** : on utilise le mode `dry-run` qui sauvegarde l'Excel sur disque mais n'envoie pas.
- **Pas d'appel LLM réel en dev** : le décorateur `@cached_llm_response` cache les réponses Groq dans un dossier `tests/.cache/llm/` ; les rejoue offline.

Bilan : un Codespace gratuit suffit pour 100% du développement et des tests. Le seul moment où le code touche internet réellement, c'est en prod sur Railway.

---

## 6. Disaster recovery

Si Railway tombe ou si vous voulez migrer ailleurs un jour :

- **Code** : déjà sur GitHub, indépendant.
- **DB** : `pg_dump` depuis Railway → import vers n'importe quel Postgres (Render, Supabase, AWS RDS).
- **Secrets** : à recopier dans le nouvel environnement.
- **Cron** : APScheduler tourne en process Python, donc partout où Python tourne.

Le projet est conçu pour être **portable**, pas verrouillé à Railway. Si un jour UGFS veut héberger en interne ou sur AWS, on déplace en 2 jours.
