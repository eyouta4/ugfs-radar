# 05 — Guide utilisateur UGFS-Radar

> Document pour l'**équipe UGFS** (analystes, direction, partenaires).
> **Aucune compétence technique requise.**

---

## Qu'est-ce qu'UGFS-Radar ?

UGFS-Radar est un **agent intelligent** qui :

1. 🔍 **Cherche** chaque semaine sur Internet les nouvelles opportunités d'investissement et de financement (AOs, grants, mandats) pertinentes pour UGFS
2. 🧠 **Analyse** chaque opportunité : extrait les critères clés (deadline, géographie, ticket, partenaires…)
3. 📊 **Note** chacune sur 100 selon vos priorités stratégiques
4. 📧 **Envoie** chaque lundi matin un fichier Excel synthétique à l'équipe
5. 🎯 **Apprend** de vos décisions : plus vous lui dites « Go / No-Go », plus il se calibre sur votre intuition stratégique

---

## Ce que vous recevez

### 📨 Email du lundi matin (7h, heure de Tunis)

> **Sujet** : *UGFS-Radar · Édition du 27/04/2026 · 23 opportunités · ⚠️ 2 urgentes*
>
> *Bonjour, voici la synthèse hebdomadaire... [Top 3 cités] ... Fichier Excel joint.*

### 📎 Fichier Excel (`UGFS-Radar_2026-04-27.xlsx`)

4 onglets :

| Onglet | Contenu | Pour qui |
|--------|---------|----------|
| 1. **Dashboard** | Synthèse, KPI, Top 5 | Direction, vue d'ensemble rapide |
| 2. **Toutes opportunités** | Tableau exhaustif trié par score, **avec colonne pour vos décisions Go/No-Go** | Équipe en réunion hebdo |
| 3. **Fiches détaillées** | Une fiche structurée par opportunité (résumé, éligibilité, justification IA) | Analyste avant submit |
| 4. **Historique** | Comparaison avec vos soumissions passées | Calibration mémoire |

### 🚨 Alertes Teams (si activé)

Une carte est postée immédiatement dans le canal `#ugfs-radar-alertes` dès qu'une opportunité **urgente** (deadline ≤ 7 jours) est détectée.

---

## Comment UGFS-Radar décide du score ?

Chaque opportunité est notée sur **100 points**, selon 8 critères pondérés :

| Critère | Poids | Question posée |
|---------|------:|----------------|
| Véhicule UGFS matché | 25 % | L'AO matche-t-il un de nos véhicules actifs (TGF, Blue Bond, Seed of Change, NEW ERA) ? |
| Géographie | 20 % | Tunisie / Maghreb (primaire) → Afrique élargie (secondaire) → Europe (synergie) ? |
| Thème | 20 % | Vert (50%), Bleu (30%), Généraliste (20%) ? |
| Partenaires | 10 % | GIZ, AfDB, GCF, AFD, OSS… mentionnés ? |
| Faisabilité deadline | 10 % | Avons-nous le temps de soumettre proprement ? |
| Ticket dans sweet spot | 5 % | 500 K – 50 M USD ? |
| Langue | 5 % | FR/EN principalement |
| Similarité avec Go passés | 5 % | Ressemble à ce qu'on a déjà gagné ? |

Une opportunité est **automatiquement disqualifiée (score = 0)** si :
- Géographie strictement hors scope (Asie hors MENA, Amériques)
- Éligibilité ne permet pas un asset manager (ex: « groupes locaux uniquement »)
- Deadline dépassée

---

## Que faire de votre fichier Excel ?

### Étape 1 — Le lundi matin, parcourir le Dashboard

Vue d'ensemble en 30 secondes : *combien d'opportunités, dont combien d'urgentes, top 3*.

### Étape 2 — Réunion hebdo : ouvrir « Toutes opportunités »

Dans cet onglet, **trois zones d'action** :

```
| ID | Score | Titre | ... | Décision interne (Go/No-Go) | Raison décision |
|  1 |   85  |   X   |     |  ↓ Dropdown : GO              |  Bonne synergie  |
|  2 |   72  |   Y   |     |  ↓ Dropdown : NO_GO           |  Trop tard       |
```

→ Pour chaque ligne, choisir **GO / NO_GO / BORDERLINE / SUBMITTED** dans la dropdown
→ Optionnel : ajouter une raison courte dans la dernière colonne

### Étape 3 — Renvoyer le fichier

Deux options :

#### Option A — Email (recommandé)
Forwarder le fichier modifié à : **`radar-feedback@ugfs-na.com`**
(L'agent le récupère automatiquement et calibre son scoring.)

#### Option B — Upload web
Aller sur `https://ugfs-radar.up.railway.app/docs` → endpoint `/api/feedback/excel` → uploader le fichier.

→ L'agent applique vos décisions en base et ajuste ses critères.
→ Au bout de **5 décisions accumulées**, il recalibre automatiquement les pondérations.

---

## Glossaire des décisions

| Décision | Quand l'utiliser |
|----------|------------------|
| **GO** | On va soumettre (ou on a déjà soumis) |
| **NO_GO** | Pas pertinent, ne pas suivre |
| **BORDERLINE** | À creuser, pas de décision claire |
| **SUBMITTED** | Soumission envoyée — utile pour le suivi pipeline |

---

## Comment l'agent apprend-il ?

UGFS-Radar **améliore sa précision automatiquement** grâce à vos feedbacks :

```
Semaine 1 : Score initial calculé selon profil YAML par défaut
            → 23 opportunités présentées
            → Vous indiquez 4 GO + 6 NO_GO

Semaine 5 : 30 feedbacks accumulés
            → L'agent recalibre automatiquement les poids
            → Si vos GO mettent toujours en avant les partenariats GIZ/CFYE,
              le poids "partner_match" passe de 10% à 18%
            → Vos critères implicites deviennent explicites pour l'agent
```

Cette boucle s'exécute **chaque mois** automatiquement (1er du mois, 3h du matin).

---

## Que faire si...

### ... vous voulez modifier la liste des sources scrapées ?

Contacter l'équipe technique. Il suffit d'ajouter un flux RSS ou un site dans :
```
data/ugfs_profile.yaml  →  section sources
```

### ... vous voulez exclure un type de mission (ex: pas de mandats < 100K) ?

Ajouter une règle de disqualification dans `data/ugfs_profile.yaml` :
```yaml
disqualification_rules:
  - rule: "Ticket < 100K USD"
    field: "ticket_size"
    description: "Trop petit pour notre infrastructure"
```

### ... vous voulez ajouter un nouveau véhicule UGFS (ex: nouveau fonds 2027) ?

Idem dans `ugfs_profile.yaml` :
```yaml
vehicles:
  - name: "Nouveau Fonds 2027"
    code: "NF2027"
    focus: "..."
    keywords: ["...", "..."]
```

L'agent commencera immédiatement à booster les opportunités matchant ce véhicule.

### ... une opportunité est manquée par l'agent ?

Vous pouvez l'**ajouter manuellement** via :
```
POST /api/feedback/single
  { "opportunity_id": 0, "title": "...", "url": "...", "decision": "GO" }
```

→ L'opportunité entre dans le corpus et améliore la similarité future.

### ... l'email du lundi n'arrive pas ?

1. Vérifier les spams
2. Aller sur `https://ugfs-radar.up.railway.app/health` (doit retourner `{"status": "healthy"}`)
3. Si rouge → contacter l'équipe technique

---

## Calendrier d'utilisation type

```
LUNDI 07:00   📨 Email reçu — l'analyste prépare le brief
LUNDI 10:00   👥 Réunion hebdo Investments
              → revue des opportunités, décisions Go/No-Go en direct dans l'Excel
LUNDI 11:00   📤 L'analyste forward le fichier à radar-feedback@ugfs-na.com
              → l'agent enregistre vos décisions

MARDI-VENDREDI  📋 Travail de submit sur les Go décidés
                🚨 Alertes Teams en temps réel pour les nouveaux urgents

SAMEDI-DIMANCHE  💤 L'agent collecte / analyse / score en silence

LUNDI SUIVANT 07:00   📨 Nouvel email...
```

---

## FAQ rapide

**Q : Combien coûte UGFS-Radar à faire tourner ?**
R : ~ 5 €/mois (hébergement Railway). Tous les autres services sont en quota gratuit.

**Q : Mes données sont-elles sécurisées ?**
R : Oui. Hébergement UE (Frankfurt), DB chiffrée, aucun PII collecté. Voir `docs/01_ARCHITECTURE.md` section RGPD.

**Q : Puis-je faire tourner l'agent à la demande, pas seulement le lundi ?**
R : Oui. POST sur `https://ugfs-radar.up.railway.app/api/run` (token requis).

**Q : Comment voir les anciens emails ?**
R : Tous les fichiers Excel envoyés sont stockés dans Resend (`https://resend.com/emails`).

**Q : L'agent peut-il rédiger les dossiers de submit ?**
R : Pas dans cette version. Roadmap V2.

---

## Contacts

| Sujet | Contact |
|-------|---------|
| Question fonctionnelle (scoring, sources) | Chef de projet UGFS |
| Problème technique (email manquant, agent down) | Équipe IT UGFS |
| Évolution / nouveau besoin | Sponsor projet |
