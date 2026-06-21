# Legends Tunisia Bot — Project Resume

Last updated: 2026-06-21

Use this file to pick up where we left off.

---

## Project overview

Discord bot for the **Legends Tunisia** server. Main features:

- Welcome cards with custom avatar overlay (`welcome_card.py`)
- Join-to-create voice lounges and support rooms
- Verification / staff alerts in voice
- XP / leveling system with role rewards (lvl 10, 20, 30…)
- Game role picker (multi-select menu)
- Data backup to a Discord channel (`levels_database.json`)

**Entry point:** `bot.py`  
**Legacy / alternate:** `bot_all_in_one.py`

---

## Repository & branches

| Item | Value |
|------|--------|
| GitHub | https://github.com/milihamda/Legends-Tunisisa.git |
| Active branch | `first_commit` (pushed to origin) |
| Local branch also exists | `main` (older, not the deploy branch) |
| GitHub accounts used | `milihamda` (repo owner), `ahmedmili` (contributor — fork/PR workflow if needed) |

---

## Local setup

```powershell
cd legends-tunisia-bot
pip install -r requirements.txt
copy .env.example .env
# Edit .env and set DISCORD_TOKEN
python bot.py
```

**Never commit `.env`** — it is in `.gitignore`. Only `.env.example` goes to GitHub.

---

## Docker (local test)

Requires **Docker Desktop running**.

```powershell
cd legends-tunisia-bot
docker compose build
docker compose up
```

Health check: http://localhost:8080 → should return `Legends Tunisia bot is running`

Stop local `python bot.py` before running Docker or Render — **one token = one bot instance**.

---

## Render deployment

| Item | Value |
|------|--------|
| URL | https://legends-tunisia.onrender.com |
| Service | Web Service (Docker runtime) |
| Branch | `first_commit` |
| Env var | `DISCORD_TOKEN` (set in Render dashboard, not in repo) |
| Config file | `render.yaml` |

### Render settings checklist

- [ ] **Runtime:** Docker (not Python)
- [ ] **Branch:** `first_commit`
- [ ] **Environment:** `DISCORD_TOKEN` set
- [ ] **Start command:** leave empty (uses `Dockerfile` CMD)
- [ ] Stop local bot while Render is live

### Deploy history / fixes applied

1. **Push protection** — `.env` with Discord token was blocked by GitHub; removed from git history, added `.gitignore`.
2. **Port / “in progress” deploy** — Render Web Services need an open port. Added health server on `PORT`.
3. **aiohttp thread crash** — `set_wakeup_fd only works in main thread` on Linux. Fixed by using stdlib `HTTPServer` in a background thread (commit `7387040`).
4. **Docker** — Added `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `render.yaml`.
5. **Game role picker** — Fixed rate limits + `Unknown interaction` by deferring interaction and using single `member.edit(roles=...)`.

### Latest commit

```
7387040 Fix Render health server thread crash on deploy.
```

---

## Key files

| File | Purpose |
|------|---------|
| `bot.py` | Main bot logic |
| `welcome_card.py` | Welcome image generation (Pillow) |
| `levels_database.json` | XP/level data (local; resets on Render redeploy) |
| `Dockerfile` | Render / Docker build |
| `docker-compose.yml` | Local Docker run |
| `render.yaml` | Render Blueprint config |
| `.env.example` | Template for `DISCORD_TOKEN` |

---

## Known limitations & TODO

### Done recently
- [x] Git push / auth (HTTPS as `milihamda`)
- [x] Secret scanning fix (no `.env` in repo)
- [x] Render health server
- [x] Docker setup
- [x] Game role picker interaction timeout fix

### Still to verify
- [ ] Confirm Render deploy completes after commit `7387040` (no “No open ports detected”)
- [ ] Confirm https://legends-tunisia.onrender.com returns health text
- [ ] Local Docker test (Docker Desktop was not fully running last session)

### Future improvements (optional)
- [ ] Switch Render to **Background Worker** (`type: worker` in `render.yaml`) — no HTTP port needed
- [ ] Persistent storage for `levels_database.json` (Render disk or external DB)
- [ ] Merge `first_commit` → `main` on GitHub when stable
- [ ] Rotate Discord token if it was ever exposed in old commits
- [ ] Fix typo in repo name: `Legends-Tunisisa` vs `Legends-Tunisia`

---

## Common commands

```powershell
# Status
git status
git log -5 --oneline

# Commit & push (from legends-tunisia-bot)
git add .
git commit -m "your message"
git push origin first_commit

# Run locally
python bot.py

# Docker
docker compose up --build
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|--------|-----|
| `Permission denied (publickey)` | SSH key not on GitHub | Use HTTPS remote or add SSH key |
| `denied to ahmedmili` | Wrong GitHub account cached | Clear Windows Credential Manager → retry login as `milihamda` |
| `Push cannot contain secrets` | `.env` in commit | Keep `.env` local only; amend/remove from history |
| `No open ports detected` | Health server not binding | Fixed in `7387040`; redeploy |
| `Unknown interaction` on role picker | Reply took >3s | Fixed with `defer` + single role edit |
| Rate limit 429 on roles | Two bot instances or many API calls | Run only Render **or** local; not both |
| Levels reset on Render | Ephemeral filesystem | Use Discord backup channel or add persistent disk/DB |

---

## Contacts / config notes

- Bot logs in as **WeldEl7ay#0014** (name may vary)
- Guild / channel / role IDs are hardcoded at the top of `bot.py`
- Game roles defined in `GAME_ROLES` list in `bot.py`
- Admin command: `!postroles` — posts game role picker embed

---

## Next session — start here

1. Check Render logs for latest deploy of `7387040`
2. Open https://legends-tunisia.onrender.com — confirm health response
3. Test one Discord feature (welcome, role picker, voice join-to-create)
4. If all good, merge `first_commit` into `main` or open PR for Hamda to review
