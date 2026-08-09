import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

import app.db as db
from app.config import CORS_ORIGINS
from app.models import Car
from app.resources import app_dir
from app.routers import admin, public

app = FastAPI(title="Mystery Tournament Admin & Game API")


@app.exception_handler(HTTPException)
async def admin_auth_redirect(request: Request, exc: HTTPException):
    # A human landing on /admin/* without a session cookie (e.g. a bookmark,
    # or just typing the URL) should be sent to the login page, not shown a
    # bare {"detail": "..."} JSON blob. /api/* clients (the game) still get
    # normal JSON error responses -- this only special-cases the HTML side.
    if exc.status_code == 401 and request.url.path.startswith("/admin") and request.url.path != "/admin/login":
        return RedirectResponse(url="/admin/login", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# Public /api/* routes carry no cookies/secrets -- only gameplay data -- so an
# open CORS policy is safe and avoids needing to know itch.io's exact serving
# origin ahead of time. /admin/* is same-origin HTML and ignores this entirely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)

_static_dir = os.path.join(app_dir(), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


def _seed_cars():
    """Makes sure exactly 3 Car rows exist so the admin dashboard has something
    to edit on first run -- placeholder credentials, meant to be overwritten via
    /admin/cars before the event."""
    # Uses db.engine (module attribute lookup), not a bare "engine" name imported
    # at module-load time -- tests swap db.engine out for an isolated per-test
    # SQLite file, and a stale imported reference here would silently keep
    # writing to the wrong database.
    with Session(db.engine) as session:
        existing = session.exec(select(Car)).all()
        if existing:
            return
        for i in range(1, 4):
            session.add(
                Car(
                    sort_order=i,
                    label=f"Car {i}",
                    wifi_ssid=f"MysteryCar{i}",
                    wifi_password="changeme123",
                    control_url="http://192.168.4.1",
                )
            )
        session.commit()


@app.on_event("startup")
def on_startup():
    db.init_db()
    _seed_cars()


@app.get("/")
def root():
    return {"service": "mystery-tournament-backend", "admin": "/admin/", "docs": "/docs"}
