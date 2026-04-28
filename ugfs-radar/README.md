# UGFS-Radar

> Agent IA autonome de veille stratégique et sourcing automatisé d'appels d'offres pour UGFS North Africa.

**Client :** UGFS North Africa (Tunis)
**Version :** 1.0 (MVP production-ready)
**Stack :** Python 3.11 · FastAPI · PostgreSQL · Groq (Llama 3.3 70B) · Railway · GitHub Actions

---

## 🎯 Ce que fait l'agent

Chaque lundi matin à 7h00 (Tunis), UGFS-Radar :

1. **Scrape** ~15 sources (sites institutionnels EU/AfDB/IFC/BEI, plateformes spécialisées, LinkedIn public posts, Google CSE) avec filtres géographiques (Afrique, MENA, Europe) et thématiques (Asset Management, Grants, Advisory, Mandats / Green / Blue / Généraliste).
2. **Dé-duplique** vs les opportunités déjà vues (hash sémantique).
3. **Analyse** chaque nouvelle opportunité avec un LLM (Groq Llama 3.3 70B, gratuit) qui produit un résumé structuré et un score 0–100 calibré sur l'historique UGFS (44 AO réels + métadonnées internes).
4. **Détecte les urgences** : deadline ≤ 7 jours non encore traitées → email + Teams immédiat.
5. **Livre** chaque lundi un fichier Excel multi-onglets (dashboard + opportunités + fiches + historique) par email à la liste UGFS.
6. **Apprend** des décisions Go/No-Go remplies par UGFS dans l'Excel : les poids de scoring se réajustent automatiquement chaque semaine.

Tout tourne sur le **cloud** (Railway, ~7€/mois). Aucune machine locale requise.

---

## 📁 Structure du dépôt

```
ugfs-radar/
├── README.md                          ← ce fichier
├── docs/
│   ├── 00_DATA_MISSING_FROM_CLIENT.md ← liste exhaustive des inputs à demander à UGFS
│   ├── 01_ARCHITECTURE.md             ← schéma + justification senior des choix
│   ├── 02_DEV_ENVIRONMENT.md          ← setup zéro-machine-locale, Codespaces, Railway
│   ├── 03_API_KEYS_GUIDE.md           ← comment obtenir chaque clé (Groq, SendGrid, etc.)
│   ├── 04_TEAMS_INTEGRATION.md        ← Microsoft Graph API étape par étape
│   ├── 05_CLIENT_USER_GUIDE.md        ← guide non-technique pour UGFS
│   ├── 06_ROADMAP.md                  ← évolutions futures
│   └── EMAIL_TO_CLIENT.md             ← mail prêt à envoyer à UGFS
├── src/
│   ├── config/                        ← settings, critères UGFS, listes destinataires
│   ├── collectors/                    ← scrapers par source (sites, LinkedIn, Google CSE)
│   ├── analyzer/                      ← LLM scoring + comparaison historique
│   ├── delivery/                      ← Excel builder + email + Teams alerts
│   ├── storage/                       ← Postgres ORM + dedup
│   └── api/                           ← FastAPI (feedback ingestion + healthcheck)
├── tests/                             ← pytest unit + integration
├── deploy/
│   ├── Dockerfile
│   ├── railway.toml
│   ├── .github/workflows/             ← CI/CD + cron hebdo de secours
│   └── docker-compose.yml             ← pour test local optionnel
├── data/
│   ├── historical_ao.csv              ← les 44 AO UGFS extraits + enrichis
│   └── ugfs_profile.yaml              ← critères d'investissement structurés
└── scripts/
    ├── seed_historical.py             ← initialise la DB avec l'historique
    ├── run_weekly.py                  ← entry point du cron lundi 7h
    └── ingest_feedback.py             ← lit le feedback Go/No-Go de l'Excel retour
```

---

## 🚀 Démarrage en 5 minutes

```bash
# 1. Cloner depuis GitHub Codespaces (zéro install local)
gh repo clone <votre-org>/ugfs-radar
cd ugfs-radar

# 2. Configurer les secrets (.env)
cp .env.example .env
# éditer .env : GROQ_API_KEY, DATABASE_URL, SENDGRID_API_KEY, etc.

# 3. Initialiser la DB avec l'historique UGFS
python scripts/seed_historical.py

# 4. Lancer une exécution complète manuelle
python scripts/run_weekly.py --dry-run   # sans envoyer d'email
python scripts/run_weekly.py             # exécution réelle

# 5. Déployer sur Railway (1 clic)
railway up
```

---

## 📊 Coût estimé mensuel

| Poste | Service | Coût |
|---|---|---|
| Compute + scheduler | Railway Hobby | ~5 € |
| Base de données Postgres | Railway (incluse) | 0 € |
| LLM (scoring + résumés) | Groq (free tier 30 req/min) | 0 € |
| Embeddings (similarité historique) | Voyage AI free tier | 0 € |
| Email (envoi hebdo + alertes) | Resend (3000/mois gratuit) | 0 € |
| Recherche web | Google CSE (100 req/jour gratuit) | 0 € |
| Stockage Excel livrés | Railway volume (5 Go inclus) | 0 € |
| **TOTAL MVP** | | **~5–7 € / mois** |

Si UGFS veut plus tard scaler (multi-équipes, > 50 sources, GPT-4 quality) : ~30–50 €/mois.

---

## 🔐 Sécurité

- Aucune donnée UGFS jamais exposée publiquement.
- Tous les secrets via Railway env vars, jamais committés.
- Logs sans PII, retention 30 jours.
- LLM = Groq (basé EU/US, RGPD-compatible). Pour upgrade compliance, swap vers Mistral La Plateforme (basé France).

---

## 👤 Contact

Architecte/Dev : *vous*
Client : UGFS North Africa
Lien repo : `<à compléter>`
