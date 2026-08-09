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

Same backend, same code — just reachable by other devices on the same WiFi
instead of only `localhost`. Whichever laptop hosts this doesn't need
internet access itself, only a working local WiFi network (a router or even
a phone hotspot with no SIM/data plan is fine).

### Easiest: the standalone `.exe` (no Python needed on the host laptop)

`MysteryTournamentLANServer.exe` (built from `run_lan_server.py`, see "Build
a standalone .exe" below) is fully self-contained — no Python, no `pip
install`, no `.env` file to edit. Copy it to the host laptop and double-click
it. On first run it:

- Auto-generates a random 6-digit admin PIN and prints it to the console
  (saved next to the .exe in `lan_server_config.txt` so it's the same PIN on
  every subsequent run — delete that file to get a fresh one)
- Detects and prints this machine's LAN IP and the exact URL to give out
- Creates its own `local.db` SQLite file next to itself

**Keep that console window open** — closing it stops the server. Everything
else (starting rounds, editing car credentials) happens through the printed
admin URL in a browser, from any device on the network.

You do **not** need to touch `game/core/systems/cloud_client.rpy` or rebuild
the game to switch to LAN — that's what the admin dashboard's **Backend
Mode** page is for (see the main project docs). Every game client checks in
with the cloud deployment first and gets redirected to whatever LAN address
the admin set there.

### From source (for development)

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

### Either way

1. Find this laptop's LAN IP address (the `.exe` prints this for you
   automatically; from source, run `ipconfig` on Windows or `ifconfig`/
   `ip addr` on Mac/Linux and look for the WiFi adapter's IPv4 address,
   usually `192.168.x.x`)
2. Every player's device AND this host laptop must be joined to the same
   WiFi network for this to work.
3. Windows Firewall may prompt "Allow this app through Windows Defender
   Firewall?" the first time it accepts an incoming connection from another
   device — click **Allow** (for both Private and Public networks if
   prompted), or other players' joins will silently fail to reach it.
4. Admin dashboard is at `http://<that IP>:8000/admin/` — reachable from any
   device on the WiFi, not just the host laptop.

## Build a standalone .exe

Bundles Python, every dependency, and the app into one file via PyInstaller
— the result runs on a laptop with nothing preinstalled.

```
cd backend
pip install pyinstaller
pyinstaller MysteryTournamentLANServer.spec
```

Output lands at `backend/dist/MysteryTournamentLANServer.exe`. The `.spec`
file is checked into the repo so this rebuilds identically without needing
to remember the original `--add-data`/`--onefile` flags; if `run_lan_server.py`
or the bundled data files (`app/templates/`, `app/static/`) change, just
re-run the command above.

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
