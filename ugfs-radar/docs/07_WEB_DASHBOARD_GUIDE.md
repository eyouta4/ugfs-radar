# 07 — Guide du dashboard web sécurisé

> **Pour qui ?** L'équipe UGFS qui prendra les décisions Go/No-Go via l'interface web.
> **Comment y accéder ?** `https://ugfs-radar.up.railway.app` (ou domaine UGFS personnalisé)

---

## 🔐 Connexion sécurisée

### Première connexion

1. L'admin (toi ou IT UGFS) reçoit l'email avec :
   - URL d'accès
   - Adresse email + mot de passe temporaire
2. Aller à l'URL → **page de login**
3. Saisir email + mot de passe
4. Le **mot de passe doit faire au moins 12 caractères**

### Sécurité

| Mesure | Description |
|--------|-------------|
| **bcrypt** | Mots de passe hashés avec sel unique, jamais stockés en clair |
| **JWT** | Tokens de session signés, expirent en 8h |
| **Cookies sécurisés** | httpOnly (bloque XSS), secure (HTTPS only), sameSite=strict (bloque CSRF) |
| **Rate limiting** | Max 5 tentatives de login / 15 min / IP |
| **TLS 1.3** | Toutes les connexions chiffrées (HTTPS obligatoire en prod) |
| **CSP/HSTS** | Headers de sécurité contre injection et downgrade |
| **Audit log** | Chaque login/décision tracé en DB (qui, quand, IP) |

---

## 📊 Tableau de bord

Après connexion, l'écran principal montre :

```
┌─────────────────────────────────────────────────────────────────┐
│ UGFS-Radar                          alice@ugfs-na.com [Logout] │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Tableau de bord                                                │
│   Édition du 27/04/2026                                          │
│                                                                  │
│   ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐                          │
│   │ 23│ │ 14│ │  8│ │ ⚠2│ │ 18│ │  5│                          │
│   │Det│ │Qua│ │Hi │ │Urg│ │Dec│ │Pen│                          │
│   └───┘ └───┘ └───┘ └───┘ └───┘ └───┘                          │
│                                                                  │
│   📤 Upload Excel : [Choisir fichier] [Importer décisions]      │
│                                                                  │
│   Filtres : [7 jours ▼] [Score min: 0]                          │
│                                                                  │
│   ┌────┬─────────────────────┬──────────┬─────────────────────┐│
│   │ 85 │ Climate Adaptation… │ 30/04/26 │ [GO][NO-GO][BORD]   ││
│   │    │ grant · Tunisia     │ ⚠ urgent │                     ││
│   ├────┼─────────────────────┼──────────┼─────────────────────┤│
│   │ 72 │ Blue Bond Med…      │ 15/05/26 │ [GO][NO-GO][BORD]   ││
│   └────┴─────────────────────┴──────────┴─────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Workflow recommandé

### Lundi matin, 9h
1. Email reçu avec PDF Excel
2. **Se connecter** au dashboard pour vue rapide des KPI
3. Préparer le brief réunion

### Lundi 10h, réunion équipe
1. Ouvrir le dashboard sur écran
2. Pour chaque opportunité, l'équipe discute
3. **L'analyste clique GO / NO-GO / BORDERLINE / SOUMIS** en direct
4. La décision est enregistrée immédiatement (pas besoin de "sauvegarder")

### Lundi 11h, après réunion
- Tout est déjà en base. **Rien à renvoyer par email.**
- Le scoring se calibre tout seul à partir de 5 décisions accumulées.

### Alternative : workflow Excel
Si l'équipe préfère travailler dans Excel pendant la réunion :
1. Ouvrir le fichier Excel reçu par email
2. Remplir les décisions dans la colonne dropdown
3. Revenir sur le dashboard → **"Upload Excel"**
4. Sélectionner le fichier modifié
5. Toutes les décisions sont importées en un clic

---

## 🔍 Fiche détaillée d'une opportunité

Cliquer sur le titre d'une opportunité ouvre sa **fiche complète** :

- Informations clés (type, géo, secteurs, deadline, ticket, langues, véhicule, partenaires)
- Résumé exécutif (3-4 phrases)
- Pourquoi c'est intéressant pour UGFS
- Conditions d'éligibilité
- Recommandation préliminaire de l'IA + son raisonnement
- **Détail du score** : voir comment chaque critère a contribué (transparent !)
- Opportunités historiques similaires (si match avec un Go passé)
- Boutons décision Go/No-Go avec champ raison

---

## 👥 Rôles et permissions

| Rôle | Voir dashboard | Décider Go/No-Go | Upload Excel | Créer utilisateurs | Voir audit/runs |
|------|:--:|:--:|:--:|:--:|:--:|
| **Admin** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Analyst** | ✓ | ✓ | ✓ | ✗ | ✗ |
| **Viewer** | ✓ (lecture seule) | ✗ | ✗ | ✗ | ✗ |

L'admin crée les autres comptes via **Utilisateurs → Créer un nouvel utilisateur**.

---

## 🛠️ Espace administrateur

### Page "Exécutions"
- Historique des 50 derniers runs hebdomadaires
- Statut, durée, nombre d'opportunités, alertes envoyées
- **Bouton « Lancer un run manuel »** : utile pour tester ou pour rattraper un lundi férié
- Audit log : 20 derniers événements (logins, décisions, uploads)

### Page "Utilisateurs"
- Création d'utilisateurs avec rôle
- Visualisation : qui s'est connecté quand
- Permet d'auditer l'usage de l'agent

---

## 🚨 Que faire si...

### Mot de passe oublié ?
Pour le moment **pas de reset automatique** (volontaire pour MVP, simplifie la sécurité). L'admin doit en réinitialiser un nouveau via :
```bash
python -m scripts.bootstrap_admin --email user@ugfs-na.com --name "Alice" --password "NouveauMotDePasse123"
```
Le système détecte que l'utilisateur existe et propose la réinitialisation.

### Compte verrouillé après tentatives échouées ?
Attendre 15 minutes. Le compteur se reset automatiquement.

### Je suis admin et je veux désactiver un utilisateur ?
Pour l'instant, modification directe en base — fonctionnalité prévue pour V1.5.
```sql
UPDATE users SET is_active = false WHERE email = 'leaver@ugfs-na.com';
```

### L'agent ne tourne plus ?
Aller sur `/admin/runs` → si dernière exécution > 7 jours → contacter l'IT.
Ou vérifier `/health` qui retourne le statut DB+services.

### Comment savoir qui a décidé quoi ?
**Page Exécutions** → section *Événements de sécurité*.
Toutes les décisions sont tracées avec utilisateur, IP, timestamp.

---

## 📱 Mobile / tablette

Le dashboard est **responsive** : utilisable sur tablette en réunion. Les boutons décision sont assez grands pour le tactile.

---

## 🔒 Conformité

- **RGPD** : aucun PII collecté ou exposé. Audit conservé 1 an puis purgé.
- **Hébergement** : Frankfurt (UE) par défaut sur Railway, ou VPS souverain au choix.
- **Chiffrement** : TLS en transit, bcrypt pour mots de passe, JSON non chiffré au repos (DB Postgres standard).
- **Backup** : dump quotidien automatique (cf. `.github/workflows/cron-backup.yml`).
