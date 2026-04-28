# 01 — Architecture technique

## 1. Vue d'ensemble (en une phrase)

UGFS-Radar est un **agent IA modulaire orchestré par un cron hebdomadaire**, qui scrape une dizaine de sources, déduplique les opportunités, les enrichit avec un LLM (résumé + scoring), envoie un Excel par email chaque lundi, et apprend des décisions Go/No-Go renvoyées par le client. Tout sur le cloud, ~5 €/mois.

---

## 2. Schéma d'architecture

```
                          ┌─────────────────────────────────────┐
                          │      RAILWAY CLOUD (~5€/mois)        │
                          │                                      │
   Cron lundi 7h Tunis    │  ┌──────────────┐                   │
   ────────────────────►  │  │  scheduler   │ (APScheduler)     │
                          │  └──────┬───────┘                   │
                          │         │                            │
   ┌──────────────────────┼─────────┼─────────────────────────┐  │
   │                      │         ▼                         │  │
   │   COLLECT (Module 1) │  ┌──────────────┐                 │  │
   │                      │  │  collectors  │                 │  │
   │  ┌─site_scraper──┐   │  │  (asyncio)   │                 │  │
   │  ├─linkedin──────┤   │  │              │                 │  │
   │  ├─google_cse────┤   │  └──────┬───────┘                 │  │
   │  ├─eu_portal─────┤   │         │                         │  │
   │  └─...───────────┘   │         ▼                         │  │
   │                      │  ┌──────────────┐                 │  │
   │  ANALYZE (Module 2)  │  │  dedup +     │ (sha256 + emb)  │  │
   │                      │  │  ingest      │                 │  │
   │                      │  └──────┬───────┘                 │  │
   │                      │         │                         │  │
   │                      │         ▼                         │  │
   │                      │  ┌──────────────┐    ┌──────────┐ │  │
   │                      │  │  llm_scorer  │◄──►│  Groq    │ │  │
   │                      │  │ (Llama 3.3)  │    │ (free)   │ │  │
   │                      │  └──────┬───────┘    └──────────┘ │  │
   │                      │         │                         │  │
   │                      │         ▼                         │  │
   │                      │  ┌──────────────┐                 │  │
   │                      │  │  similarity  │ (Voyage emb)    │  │
   │                      │  │  vs history  │                 │  │
   │                      │  └──────┬───────┘                 │  │
   │  DELIVER (Module 3)  │         │                         │  │
   │                      │         ▼                         │  │
   │                      │  ┌──────────────┐                 │  │
   │                      │  │ excel_builder│ (openpyxl)      │  │
   │                      │  └──────┬───────┘                 │  │
   │                      │         │                         │  │
   │                      │         ▼                         │  │
   │                      │  ┌──────────────┐    ┌──────────┐ │  │
   │                      │  │  email +     │───►│  Resend  │ │  │
   │                      │  │  Teams       │    │  Graph   │ │  │
   │                      │  └──────────────┘    └──────────┘ │  │
   │                      │                                   │  │
   │  STORAGE             │  ┌──────────────────────────┐     │  │
   │                      │  │  Postgres (Railway)      │     │  │
   │                      │  │  ├ opportunities          │     │  │
   │                      │  │  ├ runs                   │     │  │
   │                      │  │  ├ feedback               │     │  │
   │                      │  │  └ scoring_weights        │     │  │
   │                      │  └──────────────────────────┘     │  │
   │                      │                                    │  │
   │  FEEDBACK (Module 5) │  ┌──────────────┐                  │  │
   │                      │  │ ingest_excel │◄── webhook       │  │
   │                      │  │  (FastAPI)   │    Resend        │  │
   │                      │  └──────────────┘                  │  │
   │                      │                                    │  │
   └──────────────────────┘                                    │  │
                          └───────────────────────────────────────┘
                                       ▲                ▲
                          ┌────────────┘                └─────────────┐
                          │                                            │
                Excel hebdo email                              Teams alert
                (To: équipe UGFS)                              (canal #alertes)
```

---

## 3. Stack technique — choix et justification senior

| Couche | Choix retenu | Alternatives écartées | Justification |
|---|---|---|---|
| **Langage** | Python 3.11 | Node.js, Go | Écosystème mûr pour IA + scraping (Playwright, BeautifulSoup, Scrapy, openpyxl, pandas, langchain) ; UGFS pourra plus tard recruter des profils Python facilement (data scientists, etc.). |
| **Framework HTTP** | FastAPI | Flask, Django | Async natif (utile pour scraping concurrent), validation Pydantic intégrée, OpenAPI auto-généré, performance proche de Go pour notre charge. |
| **Scheduler** | APScheduler (intégré au service) | Airflow, Celery beat, n8n | APScheduler suffit largement pour 1 cron hebdo + alertes urgentes. **Airflow serait surdimensionné** (15-30 €/mois supplémentaires pour rien). On garde un workflow GitHub Actions en backup au cas où le service Railway tomberait — ceinture + bretelles. |
| **LLM (résumé + scoring)** | **Groq** (Llama 3.3 70B) en primaire, fallback Mistral Large | OpenAI GPT-4, Anthropic Claude | **Free tier généreux** (30 req/min, ~14 400/jour) — largement suffisant pour 50–100 AO par semaine. Latence ~10x plus rapide qu'OpenAI grâce au custom hardware (LPU). Llama 3.3 70B est top-tier sur les benchmarks de raisonnement. **Pour montée en gamme** : on peut switcher vers Claude 3.7 Sonnet d'Anthropic en 1 ligne de code (le prompt reste le même). |
| **Embeddings (similarité historique)** | Voyage AI `voyage-3-lite` | OpenAI ada-002, Cohere | Free tier 200M tokens à vie. Multi-lingue (FR/EN/AR). Bench supérieur à OpenAI sur retrieval. |
| **Base de données** | **PostgreSQL** + extension `pgvector` | MongoDB, Supabase, Railway "shared volume" | Postgres est le couteau-suisse moderne (relationnel + JSON + vector embeddings dans le **même moteur**). Railway le fournit gratuitement avec backups inclus. **MongoDB serait inutile** : nos données sont structurées (opportunités, scores, feedback). |
| **Web scraping** | `httpx` + `selectolax` pour 80% des sites + **Playwright** pour 20% (sites JS-lourds) | Scrapy, Selenium | `httpx` async + `selectolax` (parser C ultra-rapide) = 10x Scrapy en simplicité. Playwright uniquement pour LinkedIn et sites à JS lourd. |
| **Excel building** | `openpyxl` (avec styling pro) | xlsxwriter, pandas-only | openpyxl supporte mise en forme conditionnelle, formules, validation de listes (pour le menu déroulant Go/No-Go), images, tout ce qu'on veut. |
| **Email** | **Resend** (3000/mois gratuit) | SendGrid, Mailgun, AWS SES | API moderne, free tier généreux, deliverability excellente, webhook pour ingérer le feedback (option B). SendGrid acceptable mais quota gratuit moins généreux et UI plus lourde. |
| **Teams (alertes)** | Microsoft Graph API (app-only OAuth) | Webhook Teams "incoming" | Le webhook incoming est deprecated par Microsoft (date butoir). Graph API est l'avenir et permet aussi de **lire** les canaux pour le corpus de connaissance métier. |
| **Hébergement** | **Railway** | Render, Fly.io, AWS ECS, GCP Cloud Run | Railway = le meilleur compromis simplicité × prix × Postgres inclus pour notre volume. Déploiement git-push, scheduler intégré, 5 Go de stockage inclus, zéro DevOps. **AWS/GCP/Azure** = surdimensionné, demande des compétences DevOps que ni vous ni UGFS n'avez besoin pour ce projet. |
| **CI/CD** | GitHub Actions | GitLab CI, CircleCI | Free pour repos privés < 2000 min/mois. Lance les tests à chaque push, peut servir de scheduler de secours. |
| **IDE** | GitHub Codespaces | VSCode local, Cursor cloud | **Zéro install local**, ouvre dans le navigateur, environnement Docker reproductible. Free tier 60h/mois (largement suffisant pour ce projet). |
| **Secrets** | Railway env vars + GitHub Secrets | Vault, AWS Secrets Manager | Suffisant pour notre échelle, gratuit, simple. |
| **Monitoring** | Railway logs natifs + Sentry (free tier) | Datadog, New Relic | Sentry capture les erreurs en temps réel, free tier 5k events/mois. Largement assez. |
| **Tests** | pytest + httpx-mock + VCR | unittest, behave | Standard Python moderne. VCR enregistre les vraies réponses HTTP des sources et les rejoue offline → tests rapides et déterministes. |

---

## 4. Décisions structurantes (le "pourquoi" senior)

### 4.1 Pourquoi pas Airflow ou n8n ?

**Tentation classique :** "agent IA = pipeline = Airflow".
**Réalité :** notre pipeline tourne **1 fois par semaine**, manipule ~100 items, prend ~10 minutes. Airflow apporte de la complexité (DAG, executor, metadata DB) sans bénéfice. APScheduler in-process suffit.

**n8n** est sympa pour les intégrations no-code, mais pour le scoring LLM custom et le scoring historique, on a besoin d'un vrai code Python. n8n deviendrait un goulot.

**Règle senior :** pas d'orchestrateur tant que la complexité ne le justifie pas (> 10 jobs interdépendants).

### 4.2 Pourquoi Groq plutôt qu'OpenAI ou Claude ?

- **Coût** : OpenAI GPT-4o = ~5$/1M tokens input. Pour 100 AO × 2k tokens × 4 semaines = 800k tokens/mois = ~4$. Pas ruineux mais pas zéro. Groq Llama 3.3 70B = **free** dans nos volumes.
- **Qualité** : Llama 3.3 70B est ~95% de la qualité de GPT-4o sur les tâches de classification/résumé structuré. Pour notre scoring 0–100, c'est invisible.
- **Vitesse** : Groq fait ~500 tokens/sec, OpenAI ~50. On gagne du temps sur le pipeline hebdo.
- **Ouverture** : si UGFS veut héberger un modèle on-premise plus tard pour confidentialité absolue, Llama 3.3 70B est open-weights — on n'aura pas à refaire le prompt engineering.

**Règle senior :** valoriser l'optionnalité. Groq nous laisse le choix de migrer plus tard sans casser le code (on swap juste l'endpoint OpenAI-compatible).

### 4.3 Pourquoi Postgres + pgvector et pas une vector DB dédiée (Pinecone, Weaviate, Qdrant) ?

- **Volumes** : nous aurons ~50 AO historiques + ~5k AO accumulés sur 2 ans = riens. Pgvector traite des dizaines de millions de vecteurs.
- **Coût** : Pinecone = 70$/mois minimum pour l'usage payant. Qdrant Cloud = 25$. Pgvector dans le Postgres Railway = **0$**.
- **Opérations** : 1 DB à backupper au lieu de 2.
- **Cohérence transactionnelle** : on peut INSERT une opportunité ET son embedding dans la même transaction.

**Règle senior :** ne pas multiplier les bases de données tant que le besoin n'est pas critique.

### 4.4 Pourquoi async (asyncio + httpx) plutôt que threads ou Celery ?

- **Scraping = I/O bound** (95% du temps c'est de l'attente réseau). Async donne 50× le throughput de threads pour ce profil de charge.
- **Celery** ajoute Redis/RabbitMQ et un worker process séparé. Pas justifié pour 1 run/semaine de 10 min.

### 4.5 Pourquoi Resend plutôt que SendGrid pour l'email ?

- Free tier plus généreux (3000/mois vs 100/jour SendGrid).
- API plus propre (vraiment).
- Webhook simple pour ingérer les Excels de feedback en réponse.
- DKIM/SPF auto-configurés en 5 min.

### 4.6 Pourquoi Railway plutôt qu'AWS/GCP ?

- **AWS/GCP** : 2-3 jours de DevOps pour bootstrapper (VPC, IAM, RDS, ECS, secrets manager, CloudWatch, Lambda...) → coût caché énorme pour un projet à ~5€ d'infra réelle/mois.
- **Railway** : `railway up` et c'est en prod en 30 secondes. Postgres provisionné en 1 clic. Logs centralisés. Variables d'environnement UI.
- **Trade-off accepté** : Railway n'a pas de région EU par défaut (US-East). Si UGFS exige EU pour RGPD, on bascule vers **Render** (Frankfurt) ou **Scaleway Serverless** (Paris). Le code reste identique.

---

## 5. Flux de données détaillé (1 run hebdo)

1. **T0 (lundi 7h00 Tunis)** — APScheduler déclenche `run_weekly.py`.
2. **T0 + 0s** — Récupération du `ugfs_profile.yaml` (critères) et de la dernière version des `scoring_weights` ajustés par feedback.
3. **T0 + 0s à 5min** — Lancement parallèle des collecteurs (~10 sources). Chacun retourne une liste d'opportunités candidates au format normalisé `RawOpportunity`.
4. **T0 + 5min** — Dé-duplication : pour chaque opportunité, on calcule un hash sémantique (titre + URL canonique + deadline) et on compare avec la table `opportunities`. Les nouvelles passent à l'étape suivante ; les déjà-vues sont ignorées (sauf changement de deadline → update).
5. **T0 + 5min à 8min** — Pour chaque nouvelle opportunité, appel Groq Llama 3.3 70B avec un prompt structuré (output JSON validé Pydantic) qui produit : résumé exec, critères clés, secteurs, géographies, deadline normalisée, recommandation Go/No-Go préliminaire, score 0–100.
6. **T0 + 8min** — Pour chaque opportunité, on calcule sa similarité cosine avec les embeddings des AO historiques marqués "Go" → si > 0.85 avec un Go passé, on boost le score (+10).
7. **T0 + 8min** — On INSERT toutes les nouvelles opportunités scorées dans `opportunities`. On flag les `deadline ≤ 7 jours` comme `urgent=True`.
8. **T0 + 8min** — Pour chaque opportunité urgente NEW, on poste sur Teams via Graph API.
9. **T0 + 9min** — On génère l'Excel hebdo (4 onglets) avec openpyxl.
10. **T0 + 10min** — On envoie l'Excel par email Resend à la liste UGFS.
11. **T0 + 10min** — On INSERT une ligne dans `runs` avec timestamp, nb opportunités trouvées, nb urgentes, status.

Le **feedback** arrive de manière asynchrone (mardi/mercredi) :

12. UGFS renvoie l'Excel avec les colonnes Go/No-Go remplies → webhook Resend → endpoint FastAPI `/api/feedback` → on parse l'Excel, on UPDATE chaque opportunité avec sa décision et sa raison.
13. Hebdomadairement (le dimanche soir, avant le run du lundi), un job `recalibrate_weights.py` ajuste les poids du scoring en fonction du feedback accumulé (régression logistique simple sur les features → décision).

---

## 6. Sécurité et résilience

- **Secrets** : Railway env vars (chiffrées, jamais loggés). Aucune clé en clair dans le code.
- **Rate limiting** : chaque collecteur a un `asyncio.Semaphore` qui limite à 5 requêtes parallèles par source, et un `asyncio.sleep(random.uniform(1,3))` entre requêtes. Anti-ban.
- **User-Agent rotation** : pool de UAs réalistes (`fake-useragent`).
- **Retries** : `tenacity` avec exponential backoff sur tous les appels HTTP/LLM externes.
- **Idempotence** : si le run échoue à mi-parcours, le hash sémantique évite de re-traiter les opportunités déjà ingérées au prochain run.
- **Backup DB** : Railway snapshot quotidien automatique (7 jours de rétention).
- **Monitoring** : Sentry capture toute exception non gérée. Healthcheck endpoint `/health` ping toutes les 5 min par UptimeRobot (gratuit) pour alerte si le service tombe.
- **Logs** : structlog en JSON, retention Railway 30 jours.

---

## 7. RGPD / conformité

- Aucune **donnée personnelle UGFS** stockée hors RGPD : seuls les emails de l'équipe destinataires (consentement contractuel) et le contenu des opportunités (publiques par nature).
- **Données Teams** ingérées : elles ne sortent **jamais** de Railway. Pas de transmission à OpenAI/Groq sans floutage des noms propres internes (preprocessing avant LLM).
- Si UGFS exige hébergement EU strict : on bascule sur Render Frankfurt OU Scaleway Paris. Le code est portable.
- Les LLMs (Groq, Mistral) sont contractuellement no-train-on-data sur leurs APIs payantes. **Pour le free tier Groq, vérifier les CGU au moment de la signature** (en pratique : OK pour PoC, à revoir si volumes industriels).

---

## 8. Évolutivité

L'architecture supporte sans modification jusqu'à :
- ~50 sources scrapées
- ~500 nouvelles opportunités par semaine
- ~10 utilisateurs UGFS feedbackant en parallèle

Au-delà, on ajoute (par ordre) :
1. Worker queue (Celery/Redis) pour paralléliser les LLM calls
2. Cache Redis pour les LLM réponses (clé = hash du prompt)
3. Read replica Postgres si l'API feedback monte en charge
4. CDN pour les Excels archivés (S3 + CloudFront)
5. Multi-tenant si UGFS veut faire bénéficier d'autres équipes du système

---

## 9. Roadmap technique simplifiée

| Phase | Durée | Livrable |
|---|---|---|
| **Sprint 0** | 3 jours | Setup repo, Codespaces, Railway, secrets, modèle de données, seed de l'historique |
| **Sprint 1 — Collectors** | 5 jours | 5 collecteurs prioritaires (Google CSE, EU portal, AfDB, IFC, LinkedIn public) + dédup + tests |
| **Sprint 2 — Analyzer** | 4 jours | Scoring LLM Groq + similarity historique + JSON validation |
| **Sprint 3 — Delivery** | 3 jours | Excel multi-onglets pro + email Resend + scheduler |
| **Sprint 4 — Alertes & feedback** | 3 jours | Teams Graph API + endpoint feedback + ingestion Excel retour |
| **Sprint 5 — Apprentissage** | 3 jours | Recalibration des poids + dashboard d'évolution |
| **Sprint 6 — Hardening & démo** | 4 jours | Monitoring Sentry, doc client, démo, formation équipe UGFS |
| **TOTAL** | **~5 semaines** | MVP en production |
