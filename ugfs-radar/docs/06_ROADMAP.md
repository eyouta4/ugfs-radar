# 06 — Roadmap d'évolution

> Vision produit UGFS-Radar sur 12 mois.
> MVP livré = **V1.0 (semaine 6)** : agent autonome, livraison hebdo, learning loop.
> Les versions suivantes sont des **options stratégiques** à valider avec UGFS.

---

## Vue d'ensemble

```
   Phase 1            Phase 2              Phase 3              Phase 4
   ─────────          ─────────            ─────────            ─────────
   MVP V1.0           V1.5                 V2.0                 V3.0
   (Sem 1-6)          (Sem 7-12)           (Mois 4-6)           (Mois 7-12)

   Détection          Sourcing             Co-pilote            Plateforme
   + Scoring          étendu               de submission        partagée
   + Excel            + Alertes              + Pipeline           + Multi-clients
                      enrichies            CRM intégré          (UGFS Group)
```

---

## V1.0 — MVP livré ✅

**Périmètre actuel.** Voir documents 00 à 05.

**Capacités** :
- 4 collecteurs : Google CSE, EU Funding Portal, RSS multi-sources, LinkedIn public
- Analyzer LLM Groq (Llama 3.3 70B) → extraction structurée
- Embeddings Voyage AI → recherche similarité
- Scoring déterministe 100 pts pondéré (8 critères) + boucle d'apprentissage
- Livraison Excel 4 onglets (Dashboard, Toutes opps, Fiches, Historique)
- Email hebdo HTML responsive
- Alertes Teams Adaptive Cards (optionnel)
- API feedback (upload Excel ou décision unitaire)
- Recalibration automatique des poids (régression logistique)

**Coût récurrent** : ~ 5 €/mois.

---

## V1.5 — Sourcing étendu (Sem 7-12)

**Objectif** : doubler le nombre de sources, enrichir la qualité d'analyse.

### V1.5.1 — Nouveaux collecteurs (priorité haute)
- [ ] **Newsletter ingestion** : forward d'emails newsletters (Climate KIC Hub, Devex, etc.) → ingestion automatique
- [ ] **Crunchbase scraper** (API freemium) : repérer les nouveaux fonds en levée
- [ ] **TED Europa** (Tenders Electronic Daily) : marchés publics européens grands montants
- [ ] **AfDB Pipeline** scraping direct (pas que RSS)
- [ ] **Banque mondiale Procurement Notices** (API officielle)

### V1.5.2 — Analyzer enrichi
- [ ] Extraction automatique du **budget alloué total** (pas que ticket size)
- [ ] Détection des **co-financements requis** (ex: « 30% match obligatoire »)
- [ ] Identification du **comité d'évaluation** (souvent un signal de proximité)
- [ ] Extraction des **précédents lauréats** (signal de profil-type recherché)

### V1.5.3 — Reporting
- [ ] **Onglet 5 : Pipeline** dans l'Excel — vue Kanban des opportunités en cours (DETECTED → INTERESTED → PREP → SUBMITTED → WON/LOST)
- [ ] **Diff hebdomadaire** : « 3 nouvelles depuis lundi dernier, 2 deadlines proches »
- [ ] **Heatmap** des thèmes/géographies tendances

### V1.5.4 — UX feedback
- [ ] **Web UI minimaliste** pour saisir les Go/No-Go (alternative au dropdown Excel)
- [ ] **Slash commands Teams** : `/radar GO 42` pour décider une opportunité directement depuis Teams

**Effort estimé** : ~ 6 semaines.
**Coût** : pas d'augmentation significative.

---

## V2.0 — Co-pilote de submission (Mois 4-6)

**Objectif** : ne plus seulement détecter, mais **aider à rédiger** les dossiers.

### V2.1 — Génération de pré-dossier
- [ ] Pour chaque opportunité GO, l'agent génère :
  - Un **draft de note d'intention (Expression of Interest)** en français/anglais
  - Une **trame de proposal technique** structurée selon les critères de l'AO
  - Un **checklist de documents** à fournir (statuts, KYC, lettre de soutien, etc.)
- [ ] Ces drafts sont stockés dans un dossier OneDrive/SharePoint UGFS
- [ ] L'analyste UGFS itère dessus → workflow d'approbation interne

### V2.2 — Pipeline CRM intégré
- [ ] Synchronisation bidirectionnelle avec un CRM (HubSpot, Salesforce, ou Notion)
- [ ] Tracking des dates clés : *due diligence*, *submission*, *résultat attendu*
- [ ] Notifications automatiques J-7, J-3, J-1 avant deadline
- [ ] Auto-tag « gagné » / « perdu » selon mail de retour partenaire

### V2.3 — Mémoire conversationnelle
- [ ] Chat UGFS-Radar (Claude/GPT) avec contexte permanent du historique UGFS
- [ ] L'analyste peut demander : *« Quels sont les 3 derniers Go avec GIZ ? Compare avec celui-ci. »*
- [ ] Génération de notes de comparaison automatiques pour comité

**Effort estimé** : ~ 12 semaines (3 mois).
**Coût** : ~ 30 €/mois (LLM payant pour génération longue : Claude Sonnet 4.6 ou GPT-4.1).

---

## V3.0 — Plateforme partagée UGFS Group (Mois 7-12)

**Objectif** : étendre l'agent au-delà d'UGFS North Africa.

### V3.1 — Multi-tenant
- [ ] Chaque entité UGFS (autres pays) a son propre profil YAML
- [ ] Scoring isolé par entité, mais corpus historique partagé pour bench inter-entités
- [ ] RBAC : seul l'analyste de chaque entité voit ses opportunités

### V3.2 — Réseau de partenariats
- [ ] Mode « match-making » : si UGFS-NA détecte un AO trop large pour elle seule, suggère un consortium avec d'autres entités UGFS
- [ ] Annuaire de partenaires (GIZ, AFD…) avec historique de collaborations
- [ ] Suggestion automatique de partenaires pour chaque AO

### V3.3 — Veille concurrentielle
- [ ] Détection des soumissions concurrentes via signaux publics (LinkedIn, communiqués)
- [ ] Identification des asset managers similaires en croissance
- [ ] Benchmark des fonds émergents (taille, ticket, géo)

**Effort estimé** : ~ 6 mois.
**Coût** : ~ 50 €/mois infra + ressources humaines pour onboarding multi-entités.

---

## Décisions à valider avec UGFS

À chaque jalon, point de décision avec sponsor projet :

| Question | À discuter |
|----------|-----------|
| Investissons-nous dans V1.5 (sourcing étendu) ? | Si volume insuffisant en V1 |
| Faut-il aller en V2 (co-pilote submission) ? | Dépend du ROI mesuré sur V1+V1.5 |
| Multi-tenant V3 → demande des autres entités UGFS ? | À sonder à fin Phase 2 |

---

## Métriques de succès

À mesurer dès V1 pour piloter la roadmap :

| KPI | Cible V1 | Cible V2 | Méthode |
|-----|---------:|---------:|---------|
| Opportunités détectées / semaine | 20-40 | 50-80 | Compteur DB |
| % de Go dans les top 10 score | ≥ 50 % | ≥ 70 % | Cohorte feedback |
| Délai détection → décision UGFS | < 5 jours | < 3 jours | Timestamp `client_decided_at - discovered_at` |
| Précision auto-DQ (« vrais NO_GO ») | ≥ 85 % | ≥ 95 % | Audit trimestriel |
| Tx d'opportunités urgentes manquées | < 5 % | < 1 % | Vérif manuelle quinzaine |
| Taux de submissions effectives sur Go détectés | ≥ 40 % | ≥ 60 % | CRM |

---

## Risques techniques anticipés

| Risque | V touchée | Mitigation |
|--------|-----------|-----------|
| Quotas Google CSE saturés | V1.5+ | Bing Web Search API en backup (1000 req gratuites/mois) |
| Groq rate-limit | V2 (volume LLM élevé) | Fallback Mistral → Anthropic Claude payant |
| Voyage AI changements pricing | V1+ | Backup OpenAI text-embedding-3-small |
| Sites cibles ajoutent JavaScript-only | V1.5+ | Playwright/Puppeteer en fallback |
| LinkedIn ferme les robots Google CSE | V1+ | Source d'appoint, pas critique pour fonctionnement |

---

## Conclusion

Le **MVP V1.0 délivré aujourd'hui** est un agent autonome de bout en bout.
La V1.5 est **fortement recommandée à 3 mois** pour booster le volume de détection.
Les V2 et V3 sont des **options stratégiques** à activer si UGFS valide le ROI initial.
