# 04 — Intégration Microsoft Teams

> Ce document s'adresse à **l'administrateur IT / Microsoft 365 d'UGFS**.
> Il décrit la configuration Azure AD nécessaire pour permettre à UGFS-Radar :
> - **(A)** d'envoyer des alertes dans un canal Teams
> - **(B)** de lire le corpus interne (messages + fichiers) pour calibration sémantique

L'intégration est **optionnelle**. Sans elle, UGFS-Radar fonctionne via email uniquement.

---

## Vue d'ensemble

UGFS-Radar utilise l'**API Microsoft Graph** en mode **app-only** (sans utilisateur connecté). Cela suit la pratique standard pour les agents/bots d'entreprise.

```
UGFS-Radar  ──[client_id + secret]──►  Azure AD  ──[OAuth token]──►  Microsoft Graph  ──►  Teams (lecture / écriture)
```

L'authentification est faite côté serveur. Aucun utilisateur UGFS ne se connecte.

---

## 1. Pré-requis

- Compte **Microsoft 365 Business** ou supérieur (Teams inclus)
- Rôle **Global Administrator** ou **Application Administrator** dans Azure AD
- Le canal Teams cible créé (par défaut : `#ugfs-radar-alertes`)

---

## 2. Étape 1 — Création de l'application Azure AD

1. Aller sur **https://portal.azure.com**
2. Menu → **Azure Active Directory** → **App registrations**
3. **New registration** :
   - Name : `UGFS Radar Bot`
   - Supported account types : **Single tenant** (UGFS uniquement)
   - Redirect URI : laisser vide
4. **Register**

Après création, noter sur la page d'overview :
- **Application (client) ID** → `TEAMS_CLIENT_ID`
- **Directory (tenant) ID** → `TEAMS_TENANT_ID`

---

## 3. Étape 2 — Génération du secret client

1. Dans l'app créée → **Certificates & secrets**
2. **+ New client secret**
3. Description : `ugfs-radar-prod`
4. Expiration : **24 months** (à renouveler)
5. **Add**
6. **Copier la valeur immédiatement** (elle ne sera plus visible après)

→ `TEAMS_CLIENT_SECRET = <la valeur>`

---

## 4. Étape 3 — Permissions API

1. Dans l'app → **API permissions** → **+ Add a permission**
2. **Microsoft Graph** → **Application permissions** (PAS « delegated »)
3. Cocher les permissions suivantes :

### Pour les alertes (envoi)
| Permission | Justification |
|------------|---------------|
| `ChannelMessage.Send` | Poster une carte dans le canal Teams |
| `Team.ReadBasic.All` | Lire les noms d'équipes |
| `Channel.ReadBasic.All` | Lire les noms de canaux |

### Pour la lecture du corpus (optionnel — calibration sémantique)
| Permission | Justification |
|------------|---------------|
| `ChannelMessage.Read.All` | Lire les messages des canaux UGFS |
| `Files.Read.All` | Lire les fichiers partagés (pour vectorisation du contexte métier) |

4. **Add permissions**
5. ⚠️ **Grant admin consent for [tenant]** ← **action obligatoire** par un admin global

Sans le consentement admin, l'agent recevra des erreurs `Forbidden` à l'exécution.

---

## 5. Étape 4 — Récupération des IDs Team & Channel

UGFS-Radar a besoin des IDs (pas des noms) du team et du canal cibles.

### Méthode rapide (Teams desktop)

1. Ouvrir Teams → clic droit sur le canal → **Get link to channel**
2. L'URL contient :
   ```
   https://teams.microsoft.com/l/channel/19%3aXXXXX%40thread.tacv2/...
                                          └────TEAMS_CHANNEL_ID────┘
   ?groupId=YYYYY-YYYYY-YYYYY-YYYYY
            └──────TEAMS_TEAM_ID──────┘
   ```
3. Décoder l'URL (remplacer `%3a` par `:` et `%40` par `@`)

### Méthode programmatique (via Graph Explorer)

1. Aller sur **https://developer.microsoft.com/en-us/graph/graph-explorer**
2. Se connecter avec un compte UGFS
3. Requête : `GET https://graph.microsoft.com/v1.0/teams`
4. Trouver l'équipe UGFS dans la réponse → noter son `id`
5. Requête : `GET https://graph.microsoft.com/v1.0/teams/{team_id}/channels`
6. Noter le `id` du canal cible

---

## 6. Étape 5 — Configuration UGFS-Radar

Dans Railway → service UGFS-Radar → **Variables** :

```bash
TEAMS_TENANT_ID=12345678-1234-1234-1234-123456789012
TEAMS_CLIENT_ID=abcdef12-3456-7890-abcd-ef1234567890
TEAMS_CLIENT_SECRET=Random.SecretValueCopiedFromAzure
TEAMS_TEAM_ID=YYYYY-YYYYY-YYYYY-YYYYY
TEAMS_CHANNEL_ID=19:XXXXX@thread.tacv2
TEAMS_ENABLED=true
```

Redéployer (Railway le fait automatiquement à la modification de variables).

---

## 7. Étape 6 — Test d'intégration

Une fois déployé, lancer manuellement le test :

```bash
# Depuis votre poste, après s'être connecté à Railway CLI
railway run python -c "
import asyncio
from src.delivery.teams_alerter import GraphTokenManager
import httpx

async def test():
    async with httpx.AsyncClient() as c:
        token = await GraphTokenManager().get(c)
        print('✓ Token OK :', token[:20], '...')

asyncio.run(test())
"
```

Si ça affiche un token, l'authentification fonctionne. La première alerte sera envoyée dès qu'une opportunité urgente est détectée (deadline ≤ 7 jours).

---

## 8. Format des alertes Teams

Chaque opportunité urgente génère une **Adaptive Card** dans le canal :

```
┌─────────────────────────────────────────────────┐
│ 🚨 OPPORTUNITÉ URGENTE                          │
│                                                  │
│  Climate Adaptation Fund — Tunisia 2026          │
│                                                  │
│  Programme de financement adaptation climat      │
│  Tunisie. Match TGF.                             │
│                                                  │
│  Score          85/100                           │
│  Type           grant                            │
│  Géographies    Tunisia, North Africa            │
│  Deadline       30/04/2026 ⏱ 4 jour(s)          │
│  Véhicule UGFS  TGF                              │
│  Partenaires    GIZ, Adaptation Fund             │
│                                                  │
│  [Voir la source] [Formulaire de soumission]     │
└─────────────────────────────────────────────────┘
```

Couleur d'attention :
- 🔴 Rouge : deadline ≤ 3 jours
- 🟠 Orange : 4-7 jours
- 🟢 Vert : > 7 jours (n'est plus envoyé en alerte)

---

## 9. Renouvellement du secret

Le secret client expire après 24 mois. **À renouveler avant expiration** :

1. Azure Portal → l'app `UGFS Radar Bot` → **Certificates & secrets**
2. Créer un nouveau secret
3. Mettre à jour `TEAMS_CLIENT_SECRET` dans Railway
4. Supprimer l'ancien secret expiré

⚠️ Programmer un rappel calendrier 1 mois avant l'expiration.

---

## 10. Gouvernance & sécurité

- **Audit** : Azure AD trace toutes les actions de l'app dans **Sign-in logs**
- **Révocation** : pour stopper UGFS-Radar côté Teams, désactiver l'app dans Azure → **Properties → Enabled for users to sign-in : No**
- **Périmètre** : l'app n'a accès **qu'aux ressources que vous avez explicitement autorisées** (canal Teams configuré). Elle ne peut pas lire les chats privés des utilisateurs.
- **Conformité RGPD** : aucun PII n'est lu ou stocké par l'agent. Seuls les noms de partenaires/projets passent par les embeddings (anonymisés).
