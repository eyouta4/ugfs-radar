# 03 — Guide d'obtention des clés API

> Ce document recense les **9 clés API** à obtenir pour faire tourner UGFS-Radar.
> Coût total : **0 € en mode MVP** (tous les services ont une offre gratuite suffisante pour l'usage UGFS).

---

## Récapitulatif

| Service | Usage | Coût | Quota gratuit | Priorité |
|---------|-------|------|---------------|----------|
| 1. Groq | LLM (analyse opportunités) | Gratuit | 30 req/min | 🔴 Critique |
| 2. Voyage AI | Embeddings (similarité) | Gratuit | 200M tokens/mois | 🔴 Critique |
| 3. Google CSE | Recherche web ciblée | Gratuit | 100 req/jour | 🔴 Critique |
| 4. Resend | Envoi email + pièce jointe | Gratuit | 3000 emails/mois | 🔴 Critique |
| 5. Railway | Hébergement cloud | ~5 € / mois | 5 USD/mois inclus | 🔴 Critique |
| 6. PostgreSQL Railway | Base de données | Inclus | 1 GB | 🔴 Critique |
| 7. Sentry | Monitoring erreurs | Gratuit | 5k events/mois | 🟡 Recommandé |
| 8. UptimeRobot | Surveillance santé | Gratuit | 50 monitors | 🟡 Recommandé |
| 9. Microsoft Graph | Teams (alertes urgentes) | Inclus M365 | — | 🟢 Optionnel |

**Total temps d'obtention : ~ 2 heures.**

---

## 1. Groq — clé LLM

Groq est le fournisseur LLM principal. On utilise `llama-3.3-70b-versatile` (open-source, gratuit, ~ 280 tokens/sec).

1. Aller sur **https://console.groq.com**
2. Sign in (Google ou GitHub recommandé)
3. Onglet **API Keys** → **Create API Key**
4. Nom : `ugfs-radar-prod`
5. Copier la clé `gsk_...` immédiatement (elle ne sera plus visible)

Variable d'environnement :
```bash
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

**Limites free tier** : 30 requêtes / minute, 14 400 / jour. Pour UGFS (≈ 80 opportunités/semaine), on est à ~ 12 req/semaine. Largement suffisant.

---

## 2. Voyage AI — clé Embeddings

Embeddings multilingues (FR/EN/AR) pour la similarité avec les Go passés.

1. Aller sur **https://www.voyageai.com**
2. Sign up
3. Dashboard → **API Keys** → **Create**
4. Copier la clé `pa-...`

Variable :
```bash
VOYAGE_API_KEY=pa-...
VOYAGE_MODEL=voyage-3-lite
```

**Limites free tier** : 200M tokens/mois. UGFS-Radar consomme ~ 50k tokens/semaine → 0,1 % du quota.

---

## 3. Google Custom Search Engine

Pour la recherche programmable sur les sources web (LinkedIn public, blogs partenaires, etc.).

### a) Créer la clé API

1. Aller sur **https://console.cloud.google.com**
2. Créer un projet `ugfs-radar`
3. **APIs & Services → Library** → activer **Custom Search API**
4. **APIs & Services → Credentials → Create credentials → API key**
5. Copier la clé `AIza...`

### b) Créer le moteur de recherche

1. Aller sur **https://programmablesearchengine.google.com/controlpanel/create**
2. Nommer : `UGFS Radar`
3. Cocher **Search the entire web**
4. Créer → copier l'**ID du moteur** (Search Engine ID, format `12345...:abcd...`)

Variables :
```bash
GOOGLE_CSE_API_KEY=AIza...
GOOGLE_CSE_ID=12345...:abcd...
```

**Limites free tier** : 100 requêtes / jour. UGFS-Radar : 13 requêtes/semaine. OK.

---

## 4. Resend — Email transactionnel

Pour envoyer le mail hebdo avec le fichier Excel en pièce jointe.

1. Aller sur **https://resend.com**
2. Sign up (avec l'email pro UGFS)
3. **Domains** → ajouter `ugfs-na.com` (ou domaine existant)
4. Configurer les DNS chez le registrar UGFS :
   - SPF (TXT)
   - DKIM (3 enregistrements CNAME)
   - DMARC (TXT) — optionnel mais recommandé
5. **API Keys** → **Create** → permission `Sending access`
6. Copier la clé `re_...`

Variables :
```bash
RESEND_API_KEY=re_...
EMAIL_FROM="UGFS-Radar <radar@ugfs-na.com>"
EMAIL_TO="ceo@ugfs-na.com,investments@ugfs-na.com"
EMAIL_CC=""
```

**Limites free tier** : 3000 emails / mois (UGFS : 5 / mois).

---

## 5 + 6. Railway — Hébergement cloud + Postgres

Plateforme de déploiement git-push avec PostgreSQL inclus.

1. Aller sur **https://railway.app**
2. Sign in avec GitHub
3. **New Project → Deploy from GitHub repo** → sélectionner le repo UGFS-Radar
4. **+ New → Database → PostgreSQL** (provisionne pgvector compatible)
5. La variable `DATABASE_URL` est injectée automatiquement
6. Aller sur le service web → **Variables** → ajouter toutes les autres clés API

**Coût** : ~ 5 €/mois (forfait Hobby). Inclut 5 USD de crédit (qui couvrent le run).

**Région** : choisir **Frankfurt** (UE, conformité RGPD).

---

## 7. Sentry — Monitoring erreurs (recommandé)

Capture les exceptions en production pour debug.

1. Aller sur **https://sentry.io**
2. Sign up free
3. **Create project** → Python → nommer `ugfs-radar`
4. Copier le `DSN` affiché

Variable :
```bash
SENTRY_DSN=https://abc123@o123.ingest.sentry.io/456
```

---

## 8. UptimeRobot — Surveillance (recommandé)

Vérifie toutes les 5 min que `/health` répond. Notifie par email si down.

1. Aller sur **https://uptimerobot.com**
2. Sign up free
3. **Add New Monitor** → HTTP(S)
4. URL : `https://votre-app.up.railway.app/health`
5. Interval : 5 min
6. Alert contact : email DSI UGFS

---

## 9. Microsoft Graph — Teams (optionnel)

Pour les alertes Teams temps réel des opportunités urgentes. Nécessite un admin Microsoft 365.
Voir document détaillé : **`docs/04_TEAMS_INTEGRATION.md`**.

---

## Synthèse — Fichier `.env` final

À copier dans Railway → Variables (ou en local dans `.env`) :

```bash
# === LLM ===
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# === Embeddings ===
VOYAGE_API_KEY=pa-...
VOYAGE_MODEL=voyage-3-lite

# === Search ===
GOOGLE_CSE_API_KEY=AIza...
GOOGLE_CSE_ID=12345...:abcd...

# === Email ===
RESEND_API_KEY=re_...
EMAIL_FROM="UGFS-Radar <radar@ugfs-na.com>"
EMAIL_TO="ceo@ugfs-na.com,investments@ugfs-na.com"
EMAIL_CC=

# === Database (auto-injecté par Railway) ===
DATABASE_URL=postgresql+asyncpg://...
DATABASE_URL_SYNC=postgresql+psycopg2://...

# === Monitoring ===
SENTRY_DSN=https://...
LOG_LEVEL=INFO
ENVIRONMENT=production

# === Scheduling ===
TIMEZONE=Africa/Tunis
WEEKLY_RUN_DAY=mon
WEEKLY_RUN_HOUR=7
WEEKLY_RUN_MINUTE=0

# === Scoring ===
URGENT_DEADLINE_DAYS=7
SIMILARITY_BOOST_THRESHOLD=0.85
SIMILARITY_BOOST_POINTS=10

# === Teams (optionnel) ===
TEAMS_TENANT_ID=
TEAMS_CLIENT_ID=
TEAMS_CLIENT_SECRET=
TEAMS_TEAM_ID=
TEAMS_CHANNEL_ID=
TEAMS_ENABLED=false

# === API ===
API_FEEDBACK_TOKEN=changez-ce-token-en-production
```

---

## Sécurité

- **Ne jamais committer le fichier `.env` sur Git** (il est dans `.gitignore`)
- Stocker les clés en production dans **Railway Variables** (chiffrées au repos)
- Rotation recommandée tous les 6 mois pour les clés sensibles (Resend, Microsoft Graph)
- En cas de compromission : régénérer la clé sur le service correspondant et la remplacer dans Railway → redéploiement automatique
