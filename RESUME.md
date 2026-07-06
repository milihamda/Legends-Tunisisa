# Legends Tunisia Bot — Résumé des commandes

**Préfixe :** `!`  
**Fichier principal :** `bot.py`  
**Version téléphone (simplifiée) :** `bot_all_in_one.py`

---

## Tout le monde

| Commande | Aliases | Description |
|----------|---------|-------------|
| `!ping` | — | Vérifie si le bot est en ligne. |
| `!level` | — | Affiche le niveau vocal et le temps passé en vocal. Sans `@user` → tes stats. Avec `@user` → stats de cette personne. |

---

## Rooms vocales (Join-to-Create)

| Commande | Aliases | Qui peut l'utiliser | Description |
|----------|---------|---------------------|-------------|
| `!panel` | `!controlpanel`, `!roompanel` | Propriétaire de la room | Reposte le panneau de contrôle dans le chat vocal de ta room. |
| `!clear` | `!clearchat`, `!purgechat`, `!purge` | Owner de la room **ou** Manage Messages | Supprime tous les messages du chat. Après un clear, utilise `!panel` pour remettre les boutons. |

---

## Admin (Manage Server)

| Commande | Aliases | Description |
|----------|---------|-------------|
| `!checkticketcategory` | — | Affiche la configuration de la catégorie tickets. |
| `!setnotifications` | `!mentionsonly`, `!notifmentions` | Met les notifications par défaut du serveur sur **@mentions only**. |
| `!postroles` | — | Poste le menu de sélection des rôles jeux. |
| `!syncroles` | `!syncjoinroles` | Donne les 5 rôles join aux membres qui ne les ont pas (`!syncroles` ou `!syncroles @user`). |
| `!ticketpanel` | `!go` | Poste le panneau de tickets texte. |

---

## Messages (Manage Messages)

| Commande | Aliases | Description |
|----------|---------|-------------|
| `!post` | `!say`, `!echo` | Reposte ton message au nom du bot (supprime ta commande). Supporte les fichiers attachés. |

---

## Tickets (Staff)

| Commande | Aliases | Description |
|----------|---------|-------------|
| `!closeticket` | `!cv` | Ferme le ticket actuel (à utiliser dans le channel ticket). |

---

## Giveaway (Rôle Giveaway Admin)

| Commande | Aliases | Description |
|----------|---------|-------------|
| `!giveaway` | — | Lance un giveaway via DM (prix, durée, gagnants, random/ID). |
| `!stop` | — | Arrête le giveaway en cours (host seulement). |
| `!kickuser` | — | Retire ou bloque un membre du giveaway actif. |

---

## Modération / Punishment

**Staff** = rôle Staff **ou** permission **Manage Server** / **Moderate Members** / **Ban Members**

| Commande | Aliases | Usage | Description |
|----------|---------|-------|-------------|
| `!ban` | — | `!ban @user reason` | Ban + carte punishment. |
| `!timeout` | `!to` | `!timeout @user 1h reason` | Timeout Discord. |
| `!chatmute` | `!cmute` | `!chatmute @user 30m reason` | Chat mute (rôle + timeout + suppression auto des messages). |
| `!voicemute` | `!vmute` | `!voicemute @user 1h reason` | Voice mute (rôle + server mute en vocal). |
| `!untimeout` | `!unchatmute`, `!unmutechat` | `!untimeout @user` | Retire le chat mute. |
| `!unmute` | `!unvmute`, `!unvoicemute` | `!unmute @user` | Retire le voice mute. |
| `!warn` | `!warning` | `!warn @user reason` | Avertissement + rôles automatiques. |
| `!warnings` | `!warns`, `!getwarns` | `!warnings @user` | Affiche le compteur de warnings. |
| `!clearwarn` | `!removewarn`, `!unwarn`, `!clearwarnings` | `!clearwarn @user` / `!clearwarn @user 1` | Efface les warnings et retire les rôles/mutes liés. |
| `!testpunishment` | `!testpunish` | `!testpunishment ban @user` | Prévisualise une carte punishment. |

### Système `!warn`

| Warn | Action | Cartes dans le log |
|------|--------|-------------------|
| **1** | Rôle warn 1 | WARN |
| **2** | + Rôle warn 2 | WARN |
| **3** | Retire warn 1+2, chat mute 1j + voice mute, **compteur → 0** | WARN + CHAT MUTE + VOICE MUTE (punisher: bot, reason: `3 warn`) |
| **4e warn** | Recommence le cycle à 1 | WARN |

### `!clearwarn` — sync des rôles

| Compteur après | Rôles retirés |
|----------------|---------------|
| **0/3** | Warn 1 + Warn 2 + chat mute + voice mute |
| **1/3** | Warn 2 seulement |
| **2/3** | Aucun rôle supplémentaire |

---

## Test / Debug

| Commande | Aliases | Description |
|----------|---------|-------------|
| `!testlevelup` | — | Prévisualise la carte level-up. Ex. : `!testlevelup @user 2 3` |
| `!testwelcome` | — | Envoie une carte de bienvenue test. |
| `!testpunishment` | `!testpunish` | Prévisualise une carte punishment. |

---

## Boutons du panneau vocal (Control Panel)

Quand tu rejoins un channel **Join-to-Create**, le bot crée ta room et envoie ce panneau. **Seul l'owner** peut utiliser les boutons de gestion.

| Bouton | Action |
|--------|--------|
| **Lock** 🔒 | Verrouille la room : seules les personnes **déjà dedans** peuvent rester. |
| **Unlock** 🔓 | Déverrouille — les autres peuvent rejoindre à nouveau. |
| **Rename** 📝 | Change le nom de la room (max 30 caractères). |
| **Kick** 👞 | Déconnecte un membre du vocal. |
| **Transfer** 👑 | Transfère la propriété de la room. |
| **Check Level** 📊 | Affiche ton niveau vocal (message éphémère). |

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

| Channel trigger | Nom de la room | Accès |
|-----------------|----------------|-------|
| **Create Lounge** | `🎙️\|{username} ✓` | Boy + Girl roles + owner |
| **Support** | `Support \| {username}` | Staff + owner |
| **Verification 1 / 2** | `Verify \| {username}` | Staff + owner |

- La room est **supprimée** quand tout le monde la quitte.
- Si l'owner quitte mais d'autres restent → après **60 secondes**, ownership aléatoire (lounge).
- Après restart : rooms vides supprimées, rooms occupées re-enregistrées.

### Bienvenue (`on_member_join`)

- Donne **Not Verified** + **5 rôles join** au nouveau membre.
- Envoie une **carte image de bienvenue** dans le channel welcome.

### Chat mute actif

- Si un membre a le rôle chat mute ou un timeout → le bot **supprime** ses messages dans tous les channels.

### Voice mute actif

- Si un membre a le rôle voice mute et rejoint un vocal → le bot applique un **server mute** automatique.

### Vérification vocale

- Membre **Not Verified** dans Verification 1 ou 2 → **DM aux staff**.

### Support vocal

- Membre normal dans Support → **notification aux staff**.

### Système de levels vocal

- **+1 minute** par minute en vocal actif (pas self-deaf, pas bot).
- Level-up annoncé dans **#level-log** avec carte image.
- Rôles auto : **Lv 10**, **Lv 20**, **Lv 30+**.
- Formule : Lv1 = 5 min, puis +10, +15, +20 min… entre chaque level.
- Backup auto : channel Discord + `data/levels_database.json`.

### Bot statique

- Connecté en **muet/sourd** dans son channel vocal fixe.
- Status : **Do Not Disturb**.
- Message maintenu dans le **Bot-Chat** channel.

### Au démarrage

- Charge levels + warnings.
- Nettoie les temp voice vides.
- Ré-enregistre panneaux et tickets.
- Health check HTTP sur `PORT` (Render/hosting).

---

## Version `bot_all_in_one.py` (Pydroid / téléphone)

Version **réduite** pour tourner sur téléphone :

| Commande | Description |
|----------|-------------|
| `!level` | Affiche level + XP (système simplifié). |

**Pas inclus** : modération, giveaway, tickets, punishment cards, sync roles, etc.

---

## Permissions requises pour le bot

- Manage Channels, Manage Messages, Move Members, **Mute Members**
- Manage Roles (rôles jeux, levels, warns, join, mutes)
- Manage Server (pour `!setnotifications`)
- Moderate Members (timeouts, mutes)
- Ban Members (pour `!ban`)
- Le rôle du bot doit être **au-dessus** des rôles qu'il assigne.

---

## Variables d'environnement (`.env`)

| Variable | Rôle |
|----------|------|
| `DISCORD_TOKEN` | Token du bot (obligatoire) |
| `BOT_CHAT_CHANNEL_ID` | Channel du message bot-chat |
| `BOT_CHAT_MESSAGE` | Texte du message bot-chat |
| `SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS` | `true` = auto @mentions au démarrage |
| `TICKET_CATEGORY_ID` | ID catégorie tickets (optionnel) |

---

## Preview punishment card (local)

```powershell
python preview_punishment_card.py ban
```

Génère `preview_output/ban.png` sans lancer le bot.
