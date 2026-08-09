import os
import socket
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

import datetime as _dt

from app.config import CANONICAL_CLOUD_ADMIN_URL, SCENARIO_CATALOGUE
from app.db import get_session
from app.models import BackendMode, Car, Entry, LobbyPresence, QrAward, Round
from app.resources import app_dir
from app.security import COOKIE_NAME, check_pin, make_session_cookie, require_admin
from app.services import round_service

router = APIRouter(prefix="/admin")

_templates_dir = os.path.join(app_dir(), "templates")
templates = Jinja2Templates(directory=_templates_dir)

# The join-waiting screen sends a heartbeat roughly every 1.5s -- anyone
# still "counts as waiting" if we've heard from them within the last few
# ticks. Wide enough to tolerate a missed beat or two, tight enough that
# someone who quit the game a minute ago drops off promptly.
_LOBBY_FRESHNESS = timedelta(seconds=8)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(pin: str = Form(...)):
    if not check_pin(pin):
        # 401 render with an error instead of a bare error code, since this is
        # a human filling out a form, not an API client.
        raise HTTPException(status_code=401, detail="wrong PIN")

    response = RedirectResponse(url="/admin/", status_code=303)
    response.set_cookie(COOKIE_NAME, make_session_cookie(), httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/", response_class=HTMLResponse)
def rounds_page(request: Request, db: Session = Depends(get_session), _=Depends(require_admin)):
    rounds = db.exec(select(Round).order_by(Round.created_at.desc()).limit(25)).all()
    active = round_service.get_active_round(db)

    cutoff = datetime.utcnow() - _LOBBY_FRESHNESS
    waiting_players = db.exec(
        select(LobbyPresence)
        .where(LobbyPresence.last_seen >= cutoff)
        .order_by(LobbyPresence.last_seen.asc())
    ).all()

    return templates.TemplateResponse(
        "rounds.html",
        {
            "request": request,
            "rounds": rounds,
            "active": active,
            "scenarios": SCENARIO_CATALOGUE,
            "waiting_players": waiting_players,
        },
    )


@router.post("/rounds")
def start_round(scenario_id: str = Form(...), db: Session = Depends(get_session), _=Depends(require_admin)):
    round_service.create_round(db, scenario_id)
    return RedirectResponse(url="/admin/", status_code=303)


@router.get("/partials/lobby", response_class=HTMLResponse)
def lobby_partial(request: Request, db: Session = Depends(get_session), _=Depends(require_admin)):
    cutoff = datetime.utcnow() - _LOBBY_FRESHNESS
    waiting_players = db.exec(
        select(LobbyPresence)
        .where(LobbyPresence.last_seen >= cutoff)
        .order_by(LobbyPresence.last_seen.asc())
    ).all()
    return templates.TemplateResponse(
        "_lobby_panel.html", {"request": request, "waiting_players": waiting_players}
    )


@router.get("/partials/rounds_table", response_class=HTMLResponse)
def rounds_table_partial(request: Request, db: Session = Depends(get_session), _=Depends(require_admin)):
    rounds = db.exec(select(Round).order_by(Round.created_at.desc()).limit(25)).all()
    return templates.TemplateResponse("_rounds_table.html", {"request": request, "rounds": rounds})


def _build_round_detail_context(request: Request, round_id: str, db: Session) -> dict:
    round_ = db.get(Round, round_id)
    if round_ is None:
        raise HTTPException(status_code=404, detail="round not found")

    round_ = round_service.maybe_close_round(db, round_)

    # Awards are granted the instant a player qualifies (see submit_result())
    # -- not batched at round-close -- so this needs to be built regardless
    # of round_.status, otherwise the 1st/2nd finisher's QR wouldn't show up
    # here until the whole round finished around everyone else.
    awards = db.exec(select(QrAward).where(QrAward.round_id == round_id)).all()
    cars_by_id = {c.id: c for c in db.exec(select(Car)).all()}
    awards_by_entry = {a.entry_id: (a, cars_by_id.get(a.car_id)) for a in awards}

    entries = db.exec(select(Entry).where(Entry.round_id == round_id)).all()
    # Awarded entries first (in award/arrival order -- that's what actually
    # decided who got a car now, not elapsed time), then any other correct
    # finishers who didn't get a slot, sorted by when they submitted.
    ranked = sorted(
        [e for e in entries if e.correct],
        key=lambda e: (
            awards_by_entry[e.id][0].rank if e.id in awards_by_entry else 999,
            e.submitted_at or datetime.max,
        ),
    )
    dnf = [e for e in entries if e.submitted_at and not e.correct]
    pending = [e for e in entries if not e.submitted_at]

    return {
        "request": request,
        "round": round_,
        "ranked": ranked,
        "dnf": dnf,
        "pending": pending,
        "awards_by_entry": awards_by_entry,
    }


@router.get("/rounds/{round_id}", response_class=HTMLResponse)
def round_detail(
    round_id: str, request: Request, db: Session = Depends(get_session), _=Depends(require_admin)
):
    context = _build_round_detail_context(request, round_id, db)
    return templates.TemplateResponse("round_detail.html", context)


@router.get("/partials/round_live/{round_id}", response_class=HTMLResponse)
def round_live_partial(
    round_id: str, request: Request, db: Session = Depends(get_session), _=Depends(require_admin)
):
    context = _build_round_detail_context(request, round_id, db)
    return templates.TemplateResponse("_round_live.html", context)


@router.post("/rounds/{round_id}/force_close")
def force_close(round_id: str, db: Session = Depends(get_session), _=Depends(require_admin)):
    round_ = db.get(Round, round_id)
    if round_ is None:
        raise HTTPException(status_code=404, detail="round not found")
    round_service.force_close_round(db, round_)
    return RedirectResponse(url=f"/admin/rounds/{round_id}", status_code=303)


@router.get("/leaderboard", response_class=HTMLResponse)
def all_time_leaderboard(request: Request, db: Session = Depends(get_session), _=Depends(require_admin)):
    entries = db.exec(
        select(Entry, Round)
        .where(Entry.round_id == Round.id, Entry.correct == True)  # noqa: E712
        .order_by(Entry.elapsed_seconds.asc())
    ).all()
    rows = [{"entry": e, "round": r} for e, r in entries]
    return templates.TemplateResponse("alltime.html", {"request": request, "rows": rows})


@router.get("/cars", response_class=HTMLResponse)
def cars_page(request: Request, db: Session = Depends(get_session), _=Depends(require_admin)):
    cars = db.exec(select(Car).order_by(Car.sort_order.asc())).all()
    return templates.TemplateResponse("cars.html", {"request": request, "cars": cars})


@router.post("/cars/{car_id}")
def update_car(
    car_id: int,
    label: str = Form(...),
    wifi_ssid: str = Form(...),
    wifi_password: str = Form(...),
    control_url: str = Form(...),
    db: Session = Depends(get_session),
    _=Depends(require_admin),
):
    car = db.get(Car, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="car not found")

    car.label = label
    car.wifi_ssid = wifi_ssid
    car.wifi_password = wifi_password
    car.control_url = control_url
    car.updated_at = _dt.datetime.utcnow()
    db.add(car)
    db.commit()
    return RedirectResponse(url="/admin/cars", status_code=303)


@router.get("/api/detected-lan-ip")
def detected_lan_ip(request: Request, _=Depends(require_admin)):
    """Detects the LOCAL NETWORK IP of whichever machine is running THIS
    process -- reliable, but only actually useful when this request lands
    on the LAN host laptop itself (e.g. opened via
    http://localhost:<port>/admin/backend-mode on that machine). Hit on
    Render, this would just return Render's own container-internal address,
    which is meaningless for a LAN URL -- Render has no visibility into a
    laptop on someone's home/venue WiFi, so there's no way to detect that
    address remotely; this only works run from the machine in question.

    Uses the standard "open a UDP socket toward a public address, read back
    which local interface the OS picked" trick -- no packets actually leave
    the machine (UDP connect() just makes a local routing decision), so this
    works even with a router/hotspot that has no real internet uplink.
    """
    ip = "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        pass
    finally:
        s.close()

    # Reuse whatever port this very request came in on, rather than
    # assuming 8000 -- correct even if the admin ran uvicorn on a different
    # port.
    port = request.url.port or 8000
    return JSONResponse({"ip": ip, "suggested_url": f"http://{ip}:{port}"})


def _normalize_url(url):
    if not url:
        return None
    return url.strip().rstrip("/").lower()


@router.get("/backend-mode", response_class=HTMLResponse)
def backend_mode_page(request: Request, db: Session = Depends(get_session), _=Depends(require_admin)):
    row = db.get(BackendMode, 1)
    if row is None:
        row = BackendMode()
        db.add(row)
        db.commit()
        db.refresh(row)

    # Every server running this codebase has its OWN copy of this table --
    # but only the CANONICAL cloud deployment's row is ever actually
    # consulted by game clients (see /api/backend_mode and cloud_client.rpy's
    # bootstrap). A LAN instance's own `mode` row is otherwise meaningless,
    # so showing it as "the current mode" here would be actively
    # misleading -- confirmed live: an admin on the LAN server, actually
    # serving players, saw this page say "CLOUD" (technically true of that
    # server's own unused row) and reasonably read it as "this server isn't
    # the active one," when the cloud deployment was in fact pointing
    # everyone at it. Instead, non-canonical instances get a live
    # comparison against the real, authoritative source.
    this_base = _normalize_url(str(request.base_url))
    is_canonical = this_base == _normalize_url(CANONICAL_CLOUD_ADMIN_URL)

    cloud_status = None
    if not is_canonical:
        cloud_status = {"reachable": False, "mode": None, "lan_api_base": None, "points_here": False}
        try:
            resp = httpx.get(f"{CANONICAL_CLOUD_ADMIN_URL}/api/backend_mode", timeout=4.0)
            resp.raise_for_status()
            data = resp.json()
            cloud_status["reachable"] = True
            cloud_status["mode"] = data.get("mode")
            cloud_status["lan_api_base"] = data.get("lan_api_base")
            cloud_status["points_here"] = (
                data.get("mode") == "lan" and _normalize_url(data.get("lan_api_base")) == this_base
            )
        except httpx.HTTPError:
            # Cloud unreachable -- expected if this IS the reason LAN mode
            # is in use (venue internet down). Template shows a neutral
            # "couldn't check" message rather than treating this as an error.
            pass

    return templates.TemplateResponse(
        "backend_mode.html",
        {
            "request": request,
            "mode_row": row,
            "is_canonical": is_canonical,
            "this_base": this_base,
            "cloud_status": cloud_status,
            "canonical_cloud_admin_url": CANONICAL_CLOUD_ADMIN_URL,
        },
    )


@router.post("/backend-mode")
def backend_mode_update(
    mode: str = Form(...),
    lan_api_base: str = Form(""),
    db: Session = Depends(get_session),
    _=Depends(require_admin),
):
    if mode not in ("cloud", "lan"):
        raise HTTPException(status_code=400, detail="mode must be 'cloud' or 'lan'")
    lan_api_base = lan_api_base.strip().rstrip("/")
    if mode == "lan":
        if not lan_api_base:
            raise HTTPException(status_code=400, detail="lan_api_base required when mode is 'lan'")
        if not (lan_api_base.startswith("http://") or lan_api_base.startswith("https://")):
            raise HTTPException(
                status_code=400, detail="lan_api_base must start with http:// or https://"
            )

    row = db.get(BackendMode, 1)
    if row is None:
        row = BackendMode()
    row.mode = mode
    row.lan_api_base = lan_api_base
    row.updated_at = _dt.datetime.utcnow()
    db.add(row)
    db.commit()

    # Send the admin's own browser to whichever server they just made the
    # active one -- once switched, that's the dashboard that actually shows
    # live rounds/players (this instance's own view is a separate database
    # from whichever one game clients are now using). Cross-origin, so the
    # admin session cookie won't carry over -- they'll need to log in again
    # on the destination, which the template also warns about up front.
    target_base = lan_api_base if mode == "lan" else CANONICAL_CLOUD_ADMIN_URL
    return RedirectResponse(url=f"{target_base}/admin/backend-mode", status_code=303)
