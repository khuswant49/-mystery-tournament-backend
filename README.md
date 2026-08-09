# Mystery Tournament — Backend

Replaces the old peer-hosted LAN admin/leaderboard with a real cloud service:
round lifecycle, persistent leaderboard, and automatic QR-code issuance for the
top 3 correct finishers of each round.

## Run locally

```
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then edit ADMIN_PIN/COOKIE_SECRET
uvicorn app.main:app --reload --port 8000
```

Without a `DATABASE_URL` set, it falls back to a local `local.db` SQLite file —
fine for development; use real Postgres (`DATABASE_URL`) in production.

- Admin dashboard: http://localhost:8000/admin/ (PIN from `.env`)
- API docs: http://localhost:8000/docs
- Game-facing API: `POST /api/join`, `GET /api/rounds/{id}/state`,
  `POST /api/entries/{id}/submit`, `GET /api/entries/{id}/result`

## Run on LAN (event-day fallback if venue internet is unreliable)

Same backend, same code — just bound so other devices on the same WiFi can
reach it, instead of only `localhost`. Run this on whichever laptop will act
as the host for the event (doesn't need internet access itself, only a
working local WiFi network — a router or even a phone hotspot with no SIM/
data plan is fine):

```
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then edit ADMIN_PIN/COOKIE_SECRET
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The `--host 0.0.0.0` is the important part — without it, uvicorn only
listens on `127.0.0.1` (this machine only), which is invisible to every
other device on the network even though they're on the same WiFi.

1. Find this laptop's LAN IP address:
   - Windows: open a terminal, run `ipconfig`, look for "IPv4 Address"
     under the WiFi adapter (usually `192.168.x.x`)
   - Mac/Linux: `ifconfig` or `ip addr`, same idea
2. Set `game/core/systems/cloud_client.rpy`'s `LAN_API_BASE` to
   `http://<that IP>:8000` and `USE_LAN = True`, then relaunch/rebuild the
   game so every player's copy points at it.
3. Every player's device AND this host laptop must be joined to the same
   WiFi network for this to work.
4. Windows Firewall may prompt "Allow this app through Windows Defender
   Firewall?" the first time uvicorn starts and accepts an incoming
   connection from another device — click **Allow** (for both Private and
   Public networks if prompted), or other players' joins will silently fail
   to reach it.
5. Admin dashboard is at `http://<that IP>:8000/admin/` — reachable from any
   device on the WiFi, not just the host laptop.

## Deploy (Render)

1. Push this repo, create a Render **Web Service** pointed at `backend/`, build
   command `pip install -r requirements.txt`, start command
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
2. Add a Render **Postgres** instance, copy its Internal Database URL into the
   web service's `DATABASE_URL` env var.
3. Set `ADMIN_PIN` and `COOKIE_SECRET` env vars (don't use the `.env.example`
   placeholders).
4. Use the **Starter** plan, not Free — Render's free tier sleeps after 15
   minutes idle (30-60s cold start), which is unacceptable mid-event when a
   player finishes and is waiting on a response.

## Tests

```
pytest
```
