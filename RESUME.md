# Legends Tunisia Bot — Project Resume

Last updated: 2026-06-23

Use this file to pick up where we left off.

---

## Project overview

Discord bot for the **Legends Tunisia** server. Main features:

- Welcome cards with custom avatar overlay (`welcome_card.py`)
- Join-to-create voice lounges, support rooms, and verification rooms
- **Room control panel** (Lock, Unlock, Rename, Kick, Check Level) in voice channel chat
- **Smart room lock** — room stays visible; whitelist blocks new joins; no replacement when someone leaves
- Verification / staff alerts in voice
- XP / leveling system with role rewards (lvl 10, 20, 30…)
- Game role picker (multi-select menu)
- Server default notifications → **Only @mentions** (admin command + auto on startup)
- Data backup to a Discord channel (`levels_database.json`)
- Bot stays connected 24/7 in bot voice channel + bot-chat keepalive

**Entry point:** `bot.py`  
**Legacy / alternate:** `bot_all_in_one.py`

---

## Repository & branches

| Item | Value |
|------|--------|
| GitHub | https://github.com/milihamda/Legends-Tunisisa.git |
| Active / deploy branch | `main` |
| Render branch | `main` (see `render.yaml`) |
| GitHub accounts used | `milihamda` (repo owner), `ahmedmili` (contributor — fork/PR workflow if needed) |

---

## Bot commands

| Command | Who | What |
|---------|-----|------|
| `!level [@user]` | Everyone | Show voice XP / level |
| `!panel` / `!controlpanel` | Room owner | Repost control panel in voice room chat |
| `!mentionsonly` / `!setnotifications` | Admin (Manage Server) | Set server default notifications to @mentions only |
| `!postroles` | Admin | Post game role picker menu |
| `!testlevelup` | Admin | Preview level-up card |
| `!testwelcome` | Admin | Preview welcome card |

**Room panel buttons** (voice channel chat, owner only): Lock, Unlock, Rename, Kick, Check Level

---

## Room lock behavior

1. **Lock** — saves whitelist of members currently in the room + sets user limit
2. Room **stays visible** (e.g. `5/5`)
3. Unauthorized users are **disconnected** if they try to join
4. When someone **leaves**, limit shrinks (e.g. `4/4`) — **no one can take their slot** until Unlock
5. **Unlock** — clears whitelist, removes user limit, restores join permissions

---

## Notifications note

- `!mentionsonly` sets the **server default** (mainly affects new members)
- Existing members must set manually: Server → Notification Settings → **Only @mentions**
- Bot no longer deletes/reposts messages in voice room chat (silent relay removed)

---

## Local setup

```powershell
cd "C:\Users\milih\OneDrive\Desktop\weld el 7ay\Legends-Tunisisa"
pip install -r requirements.txt
copy .env.example .env
# Edit .env and set DISCORD_TOKEN
python bot.py
```

**Never commit `.env`** — it is in `.gitignore`. Only `.env.example` goes to GitHub.

### Optional env vars (`.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DISCORD_TOKEN` | — | Required |
| `BOT_CHAT_CHANNEL_ID` | backup channel ID | Bot-chat channel |
| `BOT_CHAT_MESSAGE` | `welcome to Bot-Chat` | One-time welcome in bot-chat |
| `SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS` | `true` | Auto-set server default on startup |

---

## Docker (local test)

Requires **Docker Desktop running**.

```powershell
docker compose build
docker compose up
```

Health check: http://localhost:8080 → `Legends Tunisia bot is running`

Stop local `python bot.py` before running Docker or Render — **one token = one bot instance**.

---

## Render deployment

| Item | Value |
|------|--------|
| URL | https://legends-tunisia.onrender.com |
| Service | Web Service (Docker runtime) |
| Branch | `main` |
| Env var | `DISCORD_TOKEN` (set in Render dashboard, not in repo) |
| Config file | `render.yaml` |

### Render checklist

- [x] **Runtime:** Docker
- [x] **Branch:** `main`
- [ ] **Environment:** `DISCORD_TOKEN` set
- [ ] Stop local bot while Render is live
- [ ] After push: wait for deploy **Live** before testing Discord

### Deploy

```powershell
git add .
git commit -m "your message"
git push origin main
```

Render auto-deploys from `main`.

---

## Deploy history / fixes applied

1. **Push protection** — `.env` removed from git history; `.gitignore` added
2. **Render health server** — `HTTPServer` on `PORT` (commit `7387040`)
3. **HEAD health check** — UptimeRobot support (`93b5762`)
4. **Game role picker** — defer + single `member.edit(roles=...)`
5. **@mentions notifications** — `!setnotifications` + auto on startup (`e53c0f2`)
6. **Bot-chat spam fix** — stop re-sending message every minute (`3b512fb`)
7. **Render branch** — deploy from `main` instead of `first_commit`
8. **Room control panel** — permissions for bot, `!panel`, unique button IDs (`fa1d05d`)
9. **Room lock visibility** — user limit instead of permission-based lock (`8a88dbd`)
10. **Voice chat messages** — removed silent relay that deleted user messages (`2de51e8`)
11. **Lock whitelist** — no replacement when member leaves (`9f232d1`)

### Latest commit

```
9f232d1 Fix lock: no replacement when member leaves
```

---

## Key files

| File | Purpose |
|------|---------|
| `bot.py` | Main bot logic (~1100 lines) |
| `welcome_card.py` | Welcome image generation (Pillow) |
| `level_up_card.py` | Level-up card image |
| `levels_database.json` | XP/level data (local; also backed up to Discord) |
| `Dockerfile` | Render / Docker build |
| `docker-compose.yml` | Local Docker run |
| `render.yaml` | Render Blueprint config |
| `.env.example` | Template for env vars |

---

## Bot permissions required

Move bot role **above** Boy/Girl roles. Needs at minimum:

- Manage Channels
- Manage Server (for notification default)
- Send Messages / Read Message History (voice + text)
- Move Members (kick from voice)
- Connect (stay in bot voice channel)

---

## Known limitations & TODO

### Done recently
- [x] Deploy branch unified on `main`
- [x] Room control panel in voice chat
- [x] Room lock (visible + whitelist, no slot replacement)
- [x] Stop deleting voice room chat messages
- [x] Notification commands + auto server default
- [x] Bot-chat keepalive without minute spam

### Still to verify
- [ ] Confirm latest deploy (`9f232d1`) is Live on Render after each push
- [ ] Test lock with 3+ users: lock → one leaves → confirm no one else can join

### Future improvements (optional)
- [ ] Switch Render to **Background Worker** — no HTTP port needed
- [ ] Persistent storage for `levels_database.json` (Render disk or external DB)
- [ ] Restore `owners` dict after bot restart (for kick/lock owner check on old rooms)
- [ ] Rotate Discord token if it was ever exposed in old commits
- [ ] Fix typo in repo name: `Legends-Tunisisa` vs `Legends-Tunisia`

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|--------|-----|
| Control panel not showing | Bot lacked Send Messages on new private room | Fixed in `fa1d05d`; use `!panel` if missing |
| Panel in wrong place | It's in **voice channel chat** (💬), not a text channel | Open chat while in the voice room |
| Lock hides room | Old permission-based lock | Fixed with user limit + whitelist (`8a88dbd`, `9f232d1`) |
| Someone joins after lock + leave | Old user_limit-only lock | Push `9f232d1`; whitelist kicks unauthorized joins |
| Bot deletes chat messages | Silent lounge relay (removed) | Push `2de51e8` |
| `!mentionsonly` but still notified | Server default ≠ your personal settings | Set **Only @mentions** manually on your account |
| Command does nothing | Code not deployed | `git push origin main` → wait Render Live |
| Rate limit 429 | Two bot instances | Run only Render **or** local |
| Levels reset on Render | Ephemeral filesystem | Discord backup channel restores on startup |
| `git push` fails | No upstream | `git push --set-upstream origin main` |

---

## Contacts / config notes

- Bot logs in as **WeldEl7ay#0014** (name may vary)
- Guild / channel / role IDs hardcoded at top of `bot.py`
- Game roles in `GAME_ROLES` list in `bot.py`
- Join-to-create hubs: Lounge, Support, Verify ×2 (see `JOIN_TO_CREATE_CHANNELS`)

---

## Next session — start here

1. `git log -1 --oneline` — confirm latest commit matches Render deploy
2. https://legends-tunisia.onrender.com — health check
3. Test: create lounge → panel → lock → member leaves → try join (should fail)
4. Test: voice chat message stays (not deleted)
