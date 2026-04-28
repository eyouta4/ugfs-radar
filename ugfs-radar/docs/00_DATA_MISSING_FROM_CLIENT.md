# 00 — Données et accès à demander à UGFS avant développement

> **Objectif :** rassembler en UN SEUL aller-retour tout ce qu'il faut pour démarrer le projet sans blocage.

Ce document est le **brief technique** que l'on transmet à UGFS. Il est structuré pour qu'ils puissent répondre point par point. Un mail prêt à envoyer est fourni dans `EMAIL_TO_CLIENT.md`.

---

## A. Critères d'investissement précis (paramétrage du scoring)

### A.1 Périmètre cible (à confirmer/préciser)

D'après les documents reçus, on a déjà :

- **Types d'AO** : Asset Management, Grants, Advisory, Mandats
- **Thématiques** : Green, Blue, Généraliste
- **Géographies** : Afrique, MENA, Europe
- **Ticket** : aucune restriction (toutes opportunités)

**Questions à clarifier :**

1. **Pondération des thématiques.** Pour le scoring, quelle est la priorité relative entre les AO **Green** (Tunisia Green Fund) et **Blue** (Blue Bond) ? On voit dans l'historique que beaucoup de soumissions ont été faites pour TGF — est-ce le pilier #1 actuellement ? Donner un % approximatif (ex : Green 50% / Blue 30% / Généraliste 20% du focus).
2. **Pays prioritaires DANS l'Afrique et la MENA.** UGFS NA est basé à Tunis ; on cible toute l'Afrique + MENA, mais y a-t-il un sous-ensemble prioritaire (Tunisie, Maghreb, Sahel, Afrique de l'Ouest francophone, etc.) ? Cela permet de booster le score des AO sur ces zones.
3. **Langue préférée des AO.** Français exclusivement ? FR + EN ? Un AO en arabe ou portugais doit-il être ignoré, downgradé, ou traité comme les autres ?
4. **Taille de fonds / véhicules portés actuellement.** Pour calibrer le scoring "alignement véhicule", lister :
    - **TGF (Tunisia Green Fund)** — taille cible, secteurs, statut (en levée / en investissement)
    - **Blue Bond** — taille, statut
    - **Seed of Change** — taille, statut
    - **NEW ERA Fund** — taille, statut
    - **Tout autre véhicule en levée ou en gestion**
5. **Critères de DISQUALIFICATION automatique** (= score = 0, pas la peine d'analyser plus loin) :
    - Géographies hors scope (ex : Asie hors MENA, Amériques) ? → si oui lesquelles
    - Types non éligibles (ex : YCJF qui exige des "groupes locaux" — UGFS n'est pas éligible)
    - Cas particuliers à filtrer en amont

### A.2 Profil partenaires/co-investisseurs cibles

D'après les documents : GIZ, CFYE, OSS, MSF, WSU, Galite Partners, Cibola, Ardian, Molten, Greenshore, Enlight Ventures, Anesvad, Sabou Capital, Verdant Capital, etc.

**Question :** confirmer la liste **prioritaire** des partenaires pertinents (top 20). Toute mention de ces noms dans une opportunité = boost de score.

---

## B. Sources à scraper (à confirmer/compléter)

D'après les documents (CSV historique) UGFS suit déjà ces sources :

- **LinkedIn** : posts publics de comptes spécialisés (`global-grants-and-opportunities-for-africa`, `africagreenembassy`, `funds-for-impact`, `bridger-pennington`, `entrepreneurs-catalyst-hub`, etc.)
- **Sites institutionnels** : Climate KIC, AfDB, AFD, IFC, BEI, EU Funding Portal (Horizon Europe), Convergence, Adaptation Fund, Mitigation Action Facility, GCF, CIEIF, DRK, Smart Africa, ESTDEV, Finnpartnership, Common Fund for Commodities, etc.
- **Recherche Google** : termes type "call for proposals 2026 climate Africa", "green fund Africa grant", etc.

**Questions :**

1. **Sources à AJOUTER** que l'agent ne couvre pas encore et qu'UGFS aimerait suivre. Lister les URLs.
2. **Sources à EXCLURE** (sites jugés non pertinents, à blacklister).
3. **Comptes LinkedIn / Twitter / Newsletter** spécifiques que l'équipe suit aujourd'hui manuellement et qu'on doit intégrer.
4. **Confirmer les fréquences** : est-ce qu'un check **hebdomadaire le lundi matin** est suffisant, ou veut-on un check quotidien avec digest hebdo ?

---

## C. Fichiers historiques (entraînement)

Reçu :

- ✅ `Tableau_de_synthèse_des_opportunités_de_financement_et_appels_doffres_Sheet2.csv` (44 AO avec statut Soumis / Réponse négative reçue / Éligible / Non éligible)
- ✅ `Prospections_UGFS_2024.xlsx` (CRM partenaires/investisseurs, 30+ onglets)
- ✅ `Développement_AI_AO_et_funding.docx` (cahier des charges)
- ✅ `sprint_AO.pptx` (méthodologie)

**À demander en complément :**

1. **Pour chaque AO du CSV historique** : UGFS a-t-il une **décision finale formalisée** (Go / No-Go / Borderline) **et la raison** ? Le doc parle de "50 AO classés" — actuellement on n'a que le statut "Soumis/Pas soumis" pour 44 AO, sans toujours la raison explicite. **C'est critique pour entraîner le scoring.**
   - Solution rapide : un Excel à 3 colonnes : `Nom AO | Décision (Go/No-Go/Borderline) | Raison (1 phrase)`.
2. **Lettres de réponse négative reçues** (Fund Launch Partners est mentionné 2 fois comme refusé) : utile pour comprendre les patterns d'échec.
3. **Critères d'éligibilité INTERNES** non formalisés : qu'est-ce qui fait qu'un AO est immédiatement classé No-Go en interne sans débat ? (ex : "deadline < 14 jours = on ne soumet jamais", "tickets < 100k$ = on ne va pas")

---

## D. Destinataires email + canal Teams

1. **Liste des destinataires de l'email hebdomadaire du lundi matin** : prénom, nom, fonction, email. Distinguer si possible :
   - Destinataires principaux (`To`) — ceux qui prennent les décisions Go/No-Go
   - Destinataires en copie (`Cc`) — pour information
2. **Sender / from address** : on enverra depuis `radar@ugfs-na.com` ou un alias dédié type `radar-ai@ugfs-na.com`. Confirmer le domaine et qui peut configurer les enregistrements DNS (SPF/DKIM) côté UGFS.
3. **Canal Microsoft Teams pour les alertes urgentes** : UGFS a déjà donné l'accès aux discussions Teams. Préciser :
   - Le **tenant ID** Microsoft 365 d'UGFS (admin IT)
   - Le **canal cible** où poster les alertes (ex : équipe "Sourcing AO", canal "🚨 Alertes urgentes")
   - Si possible, ouvrir un **app registration Azure AD** pour notre agent (on fournira les permissions Graph API exactes — voir doc `04_TEAMS_INTEGRATION.md`)

---

## E. Microsoft Teams — corpus de connaissance métier

UGFS a accepté qu'on utilise leurs discussions Teams comme corpus de calibration de l'agent (vocabulaire, priorités, décisions internes).

**À obtenir de l'IT UGFS :**

1. **Consentement formel** par écrit (email du DG ou admin IT) précisant :
   - Périmètre des canaux/équipes accessibles
   - Période d'historique à exporter (ex : 12 derniers mois)
   - Que les données restent stockées sur Railway et ne sont jamais transmises à des tiers
2. **App registration Azure AD** avec ces permissions Microsoft Graph (application, pas déléguées) :
   - `Channel.ReadBasic.All`
   - `ChannelMessage.Read.All`
   - `Files.Read.All` (pour les fichiers partagés dans Teams)
   - `Team.ReadBasic.All`
3. **Client ID + Client Secret + Tenant ID** de cette app registration.

Le document `docs/04_TEAMS_INTEGRATION.md` contient le pas-à-pas exact pour l'admin IT.

---

## F. Process feedback Go/No-Go (boucle d'apprentissage)

D'après le besoin : *"l'interface de feedback go/no-go doit être ultra-simple, l'input via le fichier Excel lui-même"*.

**Mécanique proposée (à valider) :**

- L'Excel hebdomadaire envoyé le lundi contient une colonne `Décision UGFS` (Go / No-Go / Borderline) et une colonne `Raison`, vides.
- Pendant la réunion d'équipe UGFS, on remplit ces colonnes.
- L'Excel est renvoyé à `feedback@ugfs-radar.com` (alias dédié), OU déposé dans un dossier OneDrive partagé, OU les colonnes sont remplies directement dans un Google Sheet partagé.
- L'agent ingère ce feedback et réajuste les poids du scoring.

**Question à UGFS :** quelle option préférez-vous parmi :
1. Renvoi de l'Excel par mail (le plus simple)
2. Dossier OneDrive / SharePoint partagé (plus pro, automatisable)
3. Google Sheet partagé (le plus collaboratif et temps réel)

---

## G. Contraintes légales / RGPD

1. UGFS confirme-t-il que le scraping de **LinkedIn posts publics** + **sites web institutionnels** + **portails de funding publics** est conforme à sa politique légale interne ? On scrape uniquement du contenu **public**, pas de comptes privés, pas de DM.
2. Stockage des données : on propose Railway (US East par défaut, ou EU sur demande). Préférence UGFS ?

---

## H. Récapitulatif — Checklist côté UGFS

Pour démarrer, UGFS doit nous fournir en UN seul email :

- [ ] **A.1** : pondérations Green/Blue/Généraliste, pays prioritaires, langues, véhicules en cours, critères de disqualification
- [ ] **A.2** : top 20 partenaires/co-investisseurs cibles
- [ ] **B.1-B.4** : sources à ajouter, à exclure, comptes LinkedIn suivis, fréquence
- [ ] **C.1** : Excel `Nom AO | Décision Go/No-Go/Borderline | Raison`
- [ ] **C.2-C.3** : éventuelles lettres de refus + critères de DQ internes
- [ ] **D.1-D.2** : liste destinataires email + domaine d'envoi
- [ ] **D.3** : canal Teams cible + accès admin IT
- [ ] **E.1-E.3** : consentement Teams + App registration Azure AD
- [ ] **F** : choix mécanique de feedback (mail / OneDrive / Google Sheet)
- [ ] **G** : OK légal + préférence région cloud

Délai recommandé pour fournir tout ça : **5 jours ouvrés**. On peut démarrer la partie scraping/scoring **dès qu'on a A.1 + B + C.1**, le reste peut suivre.
