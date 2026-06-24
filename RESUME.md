# Legends Tunisia Bot — Résumé des commandes

**Préfixe :** `!`  
**Fichier principal :** `bot.py`  
**Version téléphone (simplifiée) :** `bot_all_in_one.py`

---

## Commandes texte (`!`)

| Commande | Aliases | Qui peut l'utiliser | Description |
|----------|---------|---------------------|-------------|
| `!level` | — | Tout le monde | Affiche le niveau vocal et le temps passé en vocal. Sans mention → tes stats. Avec `@user` → stats de cette personne. |
| `!panel` | `!controlpanel`, `!roompanel` | Propriétaire de la room | Reposte le panneau de contrôle dans le chat vocal de ta room. Tu dois être connecté à ta room bot-managed. |
| `!clear` | `!clearchat`, `!purgechat`, `!purge` | Owner de la room **ou** Manage Messages | Supprime tous les messages du chat (texte ou chat vocal). Après un clear dans une room, utilise `!panel` pour remettre les boutons. |
| `!post` | `!say`, `!echo` | **Manage Messages** | Lit le texte que tu écris après la commande et le reposte au nom du bot. Supprime ton message de commande. Supporte les fichiers/images attachés. |
| `!setnotifications` | `!mentionsonly`, `!notifmentions` | **Manage Server** (admin) | Met les notifications par défaut du serveur sur **@mentions only**. N'affecte que les **nouveaux** membres — chacun doit aussi régler ses notifs manuellement. |
| `!postroles` | — | **Manage Server** (admin) | Poste le menu de sélection des rôles jeux. Les membres choisissent leurs jeux via un menu déroulant. |
| `!testlevelup` | — | Admin / test | Prévisualise la carte de level-up. Exemple : `!testlevelup @user 2 3` |
| `!testwelcome` | — | Admin / test | Envoie une carte de bienvenue test dans le channel welcome (sans qu'un membre rejoigne). |

---

## Détail de chaque commande

### `!level` [@membre]
- Montre : **niveau actuel**, **temps vocal total (minutes)**, **minutes restantes** pour le prochain niveau.
- Les bots n'ont pas de profil de level.
- Le level monte automatiquement quand tu restes en vocal (voir section automatique).

### `!panel` / `!controlpanel` / `!roompanel`
- À utiliser **dans le chat de ta room vocale** temporaire.
- Tu dois être le **owner** de la room.
- Reposte l'embed + les boutons (Lock, Unlock, Rename, Kick, Transfer, Check Level).
- Utile après un `!clear` qui a supprimé le panneau.

### `!clear` / `!clearchat` / `!purgechat` / `!purge`
- Efface le maximum de messages possible (limite Discord : messages de moins de 14 jours en bulk).
- Dans une **room bot-managed** : seul l'**owner** peut clear (sauf si tu as Manage Messages).
- Dans un channel normal : il faut **Manage Messages**.
- Le bot doit aussi avoir **Manage Messages**.

### `!post` / `!say` / `!echo` [message]
- Exemple : `!post Bienvenue à tous sur le serveur !`
- Le bot **supprime** ta commande et **envoie** le même texte à sa place.
- Si tu attaches une image/fichier au message `!post`, le bot reposte le texte + les fichiers.
- Utile pour les annonces sans montrer qui a écrit la commande.

### `!setnotifications` / `!mentionsonly` / `!notifmentions`
- Change le réglage serveur → notifications par défaut = **mentions seulement**.
- Chaque membre doit encore configurer :
  - Clic sur l'icône du serveur → Notification Settings → Only @mentions
  - Clic droit sur la catégorie lounge → Notification Settings → Only @mentions

### `!postroles`
- Poste un embed **"Select your roles"** avec un menu multi-sélection.
- Jeux configurés : Free Fire, Rust, Call of Duty, GTA V, Brawlhalla, CS GO, Fortnite, Valorant, League of Legends, Minecraft.
- Le bot enlève les anciens rôles jeux et assigne ceux choisis.

### `!testlevelup` [@membre] [ancien_niveau] [nouveau_niveau]
- Commande de **test** pour voir la carte image de level-up.
- Exemple : `!testlevelup @Ahmed 5 6`

### `!testwelcome` [@membre]
- Commande de **test** pour la carte de bienvenue personnalisée (avatar + nom sur fond).

---

## Boutons du panneau vocal (Control Panel)

Quand tu rejoins un channel **Join-to-Create**, le bot crée ta room et envoie ce panneau. **Seul l'owner** peut utiliser les boutons de gestion.

| Bouton | Action |
|--------|--------|
| **Lock** 🔒 | Verrouille la room : seules les personnes **déjà dedans** peuvent rester. Personne d'autre ne peut rejoindre. |
| **Unlock** 🔓 | Déverrouille — les autres peuvent rejoindre à nouveau. |
| **Rename** 📝 | Ouvre un formulaire pour changer le nom de la room (max 30 caractères). |
| **Kick** 👞 | Menu pour choisir un membre et le **déconnecter** du vocal. |
| **Transfer** 👑 | Transfère la propriété de la room à un autre membre présent dans le vocal. |
| **Check Level** 📊 | Affiche ton niveau vocal, temps en minutes, et progression (message privé éphémère). |

---

## Menu rôles jeux (après `!postroles`)

| Action | Description |
|--------|-------------|
| Sélection multiple | Choisis un ou plusieurs jeux dans le menu déroulant. |
| Mise à jour auto | Le bot retire les anciens rôles jeux et ajoute les nouveaux. |
| Désélection totale | Si tu ne sélectionnes rien → tous les rôles jeux sont retirés. |

---

## Fonctionnalités automatiques (sans commande)

### Join-to-Create (rooms temporaires)
En rejoignant l'un de ces channels vocaux, le bot crée une **sous-room privée** :

| Channel trigger | Nom de la room | Accès |
|-----------------|----------------|-------|
| **Create Lounge** | `🎙️\|{username} ✓` | Boy + Girl roles + owner |
| **Support** | `Support \| {username}` | Staff + owner |
| **Verification 1 / 2** | `Verify \| {username}` | Staff + owner |

- `{username}` = pseudo Discord du membre (`member.name`).
- La room est **supprimée automatiquement** quand tout le monde la quitte.
- Si l'owner quitte mais d'autres restent → après **60 secondes**, l'ownership passe **aléatoirement** à quelqu'un d'autre dans la room (lounge seulement).
- **Après restart du bot** : les rooms temporaires **vides** sont supprimées ; les rooms avec des membres sont re-enregistrées.

### Bienvenue (`on_member_join`)
- Donne le rôle **Not Verified** au nouveau membre.
- Envoie une **carte image de bienvenue** dans le channel welcome.

### Vérification vocale
- Si un membre **Not Verified** entre dans Verification 1 ou 2 → **DM aux staff** avec alerte.

### Support vocal
- Si un membre normal (pas staff/support) rejoint le channel Support → **notification aux rôles staff**.

### Système de levels vocal
- **+1 minute** de temps vocal chaque minute où tu es en vocal actif (pas self-deaf, pas bot).
- Ne compte **pas** dans : Create channel, Support hub, Verification hubs, channel bot statique.
- Level-up annoncé dans **#level-log** avec carte image.
- Rôles auto assignés actuellement : **Lv 10**, **Lv 20**, **Lv 30+** (rôles Lv 40–100 configurés mais pas encore branchés dans le code).
- Formule : Lv1 = 5 min, puis +10, +15, +20 min… entre chaque level.
- Backup auto des données dans un channel Discord + fichier `levels_database.json`.

### Bot statique
- Le bot reste connecté en **muet/sourd** dans son channel vocal fixe.
- Status : **Do Not Disturb** (rouge).
- Message de bienvenue maintenu dans le **Bot-Chat** channel.

### Au démarrage
- Charge la base de levels (local ou backup Discord).
- **Nettoie les temp voice vides** et ré-enregistre celles qui ont encore des membres.
- Ré-enregistre les panneaux des rooms existantes.
- Applique les notifications @mentions (si activé dans `.env`).
- Health check HTTP sur le port `PORT` (pour Render/hosting).

---

## Version `bot_all_in_one.py` (Pydroid / téléphone)

Version **réduite** pour tourner sur téléphone. Commandes disponibles :

| Commande | Description |
|----------|-------------|
| `!level` | Affiche level + XP (système simplifié : +10 XP/min, level = XP ÷ 150). |

**Pas inclus** dans la version all-in-one : `!panel`, `!clear`, `!post`, `!postroles`, `!setnotifications`, Transfer, Support rooms, cartes level-up avancées, rôles jeux.

- Lounge nommée : `🎙️|{username} ✓`
- Nettoyage des lounges vides au démarrage.
- Boutons du panneau (version simple) : Lock, Unlock, Rename, Kick, Level — **sans** Transfer.

---

## Permissions requises pour le bot

- Manage Channels, Manage Messages, Move Members  
- Manage Roles (rôles jeux + levels + Not Verified)  
- Manage Server (pour `!setnotifications`)  
- Le rôle du bot doit être **au-dessus** des rôles qu'il assigne.

---

## Variables d'environnement (`.env`)

| Variable | Rôle |
|----------|------|
| `DISCORD_TOKEN` | Token du bot (obligatoire) |
| `BOT_CHAT_CHANNEL_ID` | Channel du message bot-chat |
| `BOT_CHAT_MESSAGE` | Texte du message bot-chat |
| `SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS` | `true` = auto @mentions au démarrage |
