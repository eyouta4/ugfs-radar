# Email à envoyer à UGFS — Récolte des inputs nécessaires au démarrage

**Objet :** UGFS-Radar | Lancement du projet — éléments à nous transmettre pour démarrer

---

Bonjour [Prénom du contact UGFS],

Faisant suite à notre cadrage sur le projet **agent IA de sourcing automatisé d'appels d'offres**, je reviens vers vous avec la liste exhaustive des éléments dont nous avons besoin de votre côté pour lancer le développement dans les meilleures conditions.

J'ai construit cette liste de manière à ce que tout puisse être traité **en un seul aller-retour**, pour ne pas créer d'allers-retours qui ralentiraient le projet. L'objectif est de démarrer le développement la semaine suivant la réception de vos retours.

J'ai analysé en détail les documents que vous nous avez transmis (cahier des charges, sprint AO, tableau des 44 opportunités historiques, fichier Prospections 2024). Cela nous donne déjà une excellente base — la liste ci-dessous ne couvre que les compléments nécessaires au paramétrage fin et aux accès techniques.

---

## 1. Critères d'investissement (paramétrage du moteur de scoring)

L'agent va scorer chaque appel d'offres détecté de 0 à 100 selon votre profil. Pour calibrer ce scoring finement :

- **Pondération des thématiques** : on voit que beaucoup des soumissions historiques concernent le Tunisia Green Fund (Green) et le Blue Bond. Pouvez-vous nous indiquer la priorité relative actuelle entre **Green / Blue / Généraliste** ? (par exemple 50% / 30% / 20% du focus de l'année)
- **Pays prioritaires DANS l'Afrique et la MENA** : est-ce que certaines zones (Maghreb, Sahel, Afrique de l'Ouest francophone, etc.) doivent peser davantage ?
- **Langues acceptées** : FR exclusivement, FR + EN, ou tout traiter ?
- **Véhicules actuellement portés par UGFS** (TGF, Blue Bond, Seed of Change, NEW ERA Fund, autres) : pour chacun, taille cible, secteurs, statut (en levée / en investissement / clôturé) — afin que l'agent reconnaisse instantanément les AO qui matchent un véhicule en cours.
- **Critères de DISQUALIFICATION automatique** : qu'est-ce qui doit immédiatement écarter une opportunité, sans même la faire monter pour analyse ? (ex : géographies hors scope, types non éligibles, deadline trop courte par principe, etc.)

## 2. Partenaires et co-investisseurs cibles

Pourriez-vous nous lister votre **top 20 des partenaires/co-investisseurs prioritaires** (GIZ, CFYE, OSS, Galite, Cibola, Greenshore, Verdant, Anesvad… on a déjà ces noms dans vos documents) ? Toute opportunité mentionnant l'un d'eux verra automatiquement son score boosté.

## 3. Sources à scraper

Nous avons identifié à partir de vos documents les sources suivantes que vous suivez déjà : LinkedIn (comptes spécialisés grants/funds), sites institutionnels (AfDB, AFD, IFC, BEI, Climate KIC, Convergence, Adaptation Fund, EU Funding Portal, Mitigation Action Facility, GCF, CIEIF, etc.), et recherches Google ciblées.

- Y a-t-il des **sources additionnelles** que vous suivez aujourd'hui manuellement et que vous voulez intégrer ?
- Y a-t-il des sources que vous voulez **explicitement exclure** ?
- Confirmez-vous que la fréquence **hebdomadaire (lundi matin)** convient ?

## 4. Historique des décisions (entraînement du modèle)

Le tableau des 44 AO que vous nous avez envoyé donne le statut "soumis / non soumis / réponse négative reçue". Pour entraîner le scoring de manière optimale, il nous faudrait pour chacune de ces 44 lignes (et idéalement quelques dizaines de plus si vous en avez) **3 colonnes simples** :

| Nom AO | Décision finale (Go / No-Go / Borderline) | Raison (1 phrase) |
|---|---|---|

Si vous en avez 50 comme mentionné dans le sprint, c'est l'idéal. Si on n'a que 30–40 lignes complètes, on s'en sort très bien.

## 5. Destinataires de l'email hebdomadaire

- **Liste des destinataires** du livrable hebdo (Excel) avec prénom / nom / fonction / email, en distinguant `To` (décideurs Go/No-Go) et `Cc` (information).
- **Adresse d'envoi souhaitée** : nous proposons `radar@ugfs-na.com` ou `radar-ai@ugfs-na.com`. Pouvez-vous nous confirmer le domaine et nous mettre en lien avec votre IT pour configurer les DNS d'envoi (SPF/DKIM, prend 15 minutes côté IT) ?

## 6. Microsoft Teams — alertes urgentes + corpus métier

Vous nous avez gentiment proposé l'accès aux Teams pour calibrer l'agent sur votre vocabulaire et vos priorités internes — c'est un atout énorme. Pour cela, votre IT doit nous fournir :

- **Tenant ID** Microsoft 365 d'UGFS
- Une **App registration Azure AD** dédiée à notre agent, avec ces permissions Microsoft Graph (en mode application) : `Channel.ReadBasic.All`, `ChannelMessage.Read.All`, `Files.Read.All`, `Team.ReadBasic.All`
- **Client ID** + **Client Secret** de cette app registration
- Le **canal Teams** où vous voulez recevoir les alertes urgentes (deadline ≤ 7 jours)

Je vous transmettrai un **document pas-à-pas** dédié à votre IT pour qu'ils puissent faire ça en 30 minutes.

Et pour votre tranquillité juridique, j'aurai besoin d'un **email du DG ou de l'admin IT** confirmant le périmètre exact de ce qu'on peut lire (canaux, période d'historique) et les engagements de confidentialité — je vous transmets également un modèle.

## 7. Mécanique de feedback hebdo (Go/No-Go)

Comme convenu, le feedback Go/No-Go est ultra-simple : vous remplissez 2 colonnes (`Décision`, `Raison`) directement dans l'Excel reçu, lors de votre réunion interne hebdomadaire. Trois options pour le retour vers l'agent :

- **Option A** : vous renvoyez l'Excel par mail à `feedback@ugfs-radar.com`. (le plus simple, je recommande)
- **Option B** : vous le déposez dans un dossier OneDrive partagé que nous monitorons.
- **Option C** : on travaille sur un Google Sheet partagé en temps réel (le plus collaboratif).

Quelle option préférez-vous ?

## 8. Conformité

Pouvez-vous me confirmer que le scraping de **contenus publics uniquement** (posts LinkedIn publics, sites institutionnels, portails de funding ouverts) est conforme à votre politique interne ? On ne scrape jamais de contenu privé, jamais de DM.

---

## Délai et prochaines étapes

Idéalement, **sous 5 jours ouvrés**, vous nous transmettez tout cela en un seul mail. Dès que nous avons les points 1, 3 et 4, le développement de la partie sourcing + scoring peut démarrer immédiatement (en parallèle, votre IT peut traiter Teams et le domaine d'envoi).

**Notre engagement de notre côté :**
- Première démo fonctionnelle (sourcing + scoring sur 3 sources pilotes, 1 livrable Excel) : **2 semaines** après réception de vos inputs.
- Mise en production complète (toutes sources, scheduler hebdo, alertes Teams, boucle d'apprentissage) : **4 à 5 semaines** après le démarrage.

N'hésitez pas si l'un des points mérite un échange rapide en visio — je peux me rendre disponible quand vous voulez sur les prochains jours.

Bien à vous,

[Votre prénom]
*Architecte IA / Lead développement — Projet UGFS-Radar*
