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
