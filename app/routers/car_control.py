"""Player-facing car control -- what a winner's QR actually points at now.

Replaces the old model where the ESP32 itself served this page over its own
WiFi AP. The car has no WiFi and no web server anymore (see
esp32_car_bluetooth/) -- this backend serves the control page, validates the
session token server-side (the car firmware has zero access control of its
own now), and hands drive commands to the admin laptop's Bluetooth bridge via
the polling model in bridge.py (not a WebSocket -- see that module's
docstring for why).
"""
from datetime import datetime
from typing import Dict, Tuple

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.config import CAR_DRIVE_WINDOW_SECONDS, CAR_TEST_PASSWORD
from app.db import get_session
from app.models import Car, CarTestSession, QrAward
from app.routers.bridge import is_bridge_connected, set_drive_state

router = APIRouter()

# A session's (car_id, created_at) never changes once granted, and a car's
# label essentially never changes during an active 5-minute drive window --
# caching both means every /drive call after the FIRST for a given session
# skips the database entirely. Measured as a real, meaningful chunk of the
# per-request latency budget on Render's free tier (shared/throttled CPU
# makes every DB round-trip relatively expensive), and every millisecond
# matters here since this is a live real-time control path, not a one-off
# request. In-memory, per-process -- fine for the same reason bridge.py's
# _car_state is (single web service instance, no need to survive a restart).
_session_cache: Dict[Tuple[int, str], datetime] = {}
_car_label_cache: Dict[int, str] = {}


def _find_session(db: Session, car_id: int, session_token: str):
    """A control session is valid if it matches EITHER a real game award or a
    password-granted test session (models.py's CarTestSession) -- both have
    the same shape for our purposes (car_id, session_token, created_at), so
    callers below don't need to care which kind they got."""
    award = db.exec(
        select(QrAward).where(QrAward.car_id == car_id, QrAward.session_token == session_token)
    ).first()
    if award is not None:
        return award
    return db.exec(
        select(CarTestSession).where(
            CarTestSession.car_id == car_id, CarTestSession.session_token == session_token
        )
    ).first()


def _remaining_seconds_from(created_at: datetime) -> float:
    elapsed = (datetime.utcnow() - created_at).total_seconds()
    return max(0.0, CAR_DRIVE_WINDOW_SECONDS - elapsed)


def _cached_car_label(db: Session, car_id: int):
    """Returns (label, car_exists). Hits the DB only on first lookup per
    process for a given car_id -- there are only ever 3 cars and their
    labels don't change mid-event, so this is safe to cache indefinitely."""
    if car_id in _car_label_cache:
        return _car_label_cache[car_id], True
    car = db.get(Car, car_id)
    if car is None:
        return None, False
    _car_label_cache[car_id] = car.label
    return car.label, True


def _cached_session_created_at(db: Session, car_id: int, session_token: str):
    """Returns the session's created_at, or None if invalid. Hits the DB only
    the first time a given (car_id, session_token) pair is seen -- a
    session's identity/creation time never changes once granted, so caching
    it is always correct, not just an approximation."""
    cache_key = (car_id, session_token)
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    session_row = _find_session(db, car_id, session_token)
    if session_row is None:
        return None
    _session_cache[cache_key] = session_row.created_at
    return session_row.created_at


# Same tank/twin-stick D-pad+Gears UI/JS already refined and bench-proven on
# the ESP32's own control page -- only the endpoints it talks to changed
# (same-origin /api/cars/... instead of a car's own 192.168.4.1).
CONTROL_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%LABEL%</title>
<style>
  body { font-family: sans-serif; background:#111; color:#eee; text-align:center; margin:0; padding:16px; }
  h1 { font-size: 20px; }
  #timer { font-size: 28px; margin: 8px 0 20px; }
  .dpad { display:flex; flex-direction:column; align-items:center; gap:8px; margin:16px 0; }
  .dpad-row { display:flex; gap:8px; }
  .dpad-spacer { width:70px; height:60px; }
  .dbtn { width:70px; height:60px; font-size:20px; border-radius:10px; border:none; background:#2a6df5; color:#fff; touch-action:none; user-select:none; -webkit-user-select:none; }
  .dbtn:active { background:#1a4dbf; }
  .dbtn.stop { background:#c0392b; }
  .dbtn.stop:active { background:#8e2419; }
  .gears { display:flex; justify-content:center; gap:10px; margin-top:14px; }
  .gear-btn { width:80px; height:44px; font-size:16px; border-radius:8px; border:2px solid #444; background:#222; color:#ccc; touch-action:none; user-select:none; -webkit-user-select:none; }
  .gear-btn.active { background:#2a6df5; border-color:#2a6df5; color:#fff; }
  #msg { color:#f39c12; min-height:20px; }
</style>
</head>
<body>
<h1>%LABEL%</h1>
<div id="timer">--:--</div>
<div id="msg"></div>

<div class="dpad">
  <div class="dpad-row"><div class="dpad-spacer"></div><button id="btn-F" class="dbtn">&#8593;</button><div class="dpad-spacer"></div></div>
  <div class="dpad-row"><button id="btn-L" class="dbtn">&#8592;</button><button id="btn-stop" class="dbtn stop">STOP</button><button id="btn-R" class="dbtn">&#8594;</button></div>
  <div class="dpad-row"><div class="dpad-spacer"></div><button id="btn-B" class="dbtn">&#8595;</button><div class="dpad-spacer"></div></div>
</div>

<div class="gears">
  <button class="gear-btn" id="gear-0" onclick="setGear(0)">Gear 1</button>
  <button class="gear-btn active" id="gear-1" onclick="setGear(1)">Gear 2</button>
  <button class="gear-btn" id="gear-2" onclick="setGear(2)">Gear 3</button>
</div>

<script>
const CAR_ID = "%CAR_ID%";
const SESSION = "%SESSION%";

var GEAR_SPEEDS = [65, 130, 195];
var gear = 1;
var held = { F: false, B: false, L: false, R: false };
var repeatTimer = null;

function anyHeld() { return held.F || held.B || held.L || held.R; }

function sendDrive(l, r) {
  fetch('/api/cars/' + CAR_ID + '/drive?session=' + encodeURIComponent(SESSION) + '&l=' + l + '&r=' + r)
    .then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (t) { throw new Error(t); });
      }
      document.getElementById('msg').innerText = '';
    })
    .catch(function (e) {
      document.getElementById('msg').innerText = 'Command rejected: ' + e.message;
    });
}

function computeAndSend() {
  var g = GEAR_SPEEDS[gear];
  var throttle = (held.F && !held.B) ? 1 : ((held.B && !held.F) ? -1 : 0);
  var steer = (held.R && !held.L) ? 1 : ((held.L && !held.R) ? -1 : 0);
  var l = Math.max(-1, Math.min(1, throttle + steer)) * g;
  var r = Math.max(-1, Math.min(1, throttle - steer)) * g;
  sendDrive(l, r);
}

function bindDirButton(id) {
  var el = document.getElementById('btn-' + id);

  function start(e) {
    e.preventDefault();
    if (held[id]) return;
    held[id] = true;
    computeAndSend();
    if (!repeatTimer) {
      repeatTimer = setInterval(function () { if (anyHeld()) computeAndSend(); }, 300);
    }
  }

  function release(e) {
    if (!held[id]) return;
    held[id] = false;
    computeAndSend();
    if (!anyHeld() && repeatTimer) {
      clearInterval(repeatTimer);
      repeatTimer = null;
    }
  }

  el.addEventListener('pointerdown', start);
  el.addEventListener('pointerup', release);
  el.addEventListener('pointercancel', release);
  el.addEventListener('pointerleave', release);
}
['F', 'B', 'L', 'R'].forEach(bindDirButton);

function setGear(idx) {
  gear = idx;
  [0, 1, 2].forEach(function (i) {
    document.getElementById('gear-' + i).classList.toggle('active', i === idx);
  });
  if (anyHeld()) computeAndSend();
}

document.getElementById('btn-stop').addEventListener('pointerdown', function (e) {
  e.preventDefault();
  held.F = held.B = held.L = held.R = false;
  if (repeatTimer) { clearInterval(repeatTimer); repeatTimer = null; }
  sendDrive(0, 0);
});

function fmt(s) {
  s = Math.max(0, Math.floor(s));
  var m = Math.floor(s / 60), r = s % 60;
  return m + ':' + (r < 10 ? '0' : '') + r;
}

function poll() {
  fetch('/api/cars/' + CAR_ID + '/status?session=' + encodeURIComponent(SESSION))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.active) {
        document.getElementById('timer').innerText = 'SESSION ENDED';
        document.getElementById('msg').innerText = 'This car is no longer under your control.';
        return;
      }
      document.getElementById('timer').innerText = fmt(d.remaining_seconds);
      if (!d.bridge_connected) {
        document.getElementById('msg').innerText = 'Car link offline -- tell an organizer.';
      }
      setTimeout(poll, 1000);
    })
    .catch(function () { setTimeout(poll, 1000); });
}
poll();
</script>
</body>
</html>
"""


@router.get("/car-control/{car_id}", response_class=HTMLResponse)
def car_control_page(car_id: int, session: str, db: Session = Depends(get_session)):
    label, exists = _cached_car_label(db, car_id)
    if not exists:
        raise HTTPException(status_code=404, detail="car not found")

    created_at = _cached_session_created_at(db, car_id, session)
    if created_at is None:
        raise HTTPException(status_code=403, detail="invalid session")

    page = CONTROL_PAGE_TEMPLATE.replace("%LABEL%", label)
    page = page.replace("%CAR_ID%", str(car_id))
    page = page.replace("%SESSION%", session)
    return HTMLResponse(page)


@router.get("/api/cars/{car_id}/drive")
def car_drive(car_id: int, session: str, l: int, r: int, db: Session = Depends(get_session)):
    # Hot path: after the first call for a given session, both lookups below
    # are pure in-memory dict reads -- no database round-trip at all. See the
    # cache docstring above for why that's always correct here, not just an
    # optimization that risks staleness.
    label, exists = _cached_car_label(db, car_id)
    created_at = _cached_session_created_at(db, car_id, session) if exists else None
    if not exists or created_at is None or _remaining_seconds_from(created_at) <= 0:
        raise HTTPException(status_code=403, detail="forbidden: missing, wrong, or expired session")

    if not is_bridge_connected():
        raise HTTPException(status_code=503, detail="car link (admin laptop) is not connected right now")

    # Always just records the latest desired state -- the bridge picks it up
    # on its next poll (bridge.py), typically within ~150-250ms.
    set_drive_state(label, l, r)
    return {"ok": True}


@router.get("/api/cars/{car_id}/status")
def car_status(car_id: int, session: str, db: Session = Depends(get_session)):
    created_at = _cached_session_created_at(db, car_id, session)
    if created_at is None:
        return {"active": False, "remaining_seconds": 0, "bridge_connected": is_bridge_connected()}

    remaining = _remaining_seconds_from(created_at)
    return {
        "active": remaining > 0,
        "remaining_seconds": int(remaining),
        "bridge_connected": is_bridge_connected(),
    }


# =================================================
# PASSWORD-GATED TEST ACCESS -- drive any car on demand without needing to
# actually win a round (testing, rehearsal, live demos, manual override).
# =================================================

TEST_ACCESS_FORM = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Car Test Access</title>
<style>
  body { font-family: sans-serif; background:#111; color:#eee; text-align:center; padding:40px 16px; }
  h1 { font-size: 22px; }
  form { display:inline-block; text-align:left; margin-top:20px; }
  label { display:block; margin:14px 0 4px; font-size:14px; color:#ccc; }
  select, input[type=password] { width:260px; padding:10px; font-size:16px; border-radius:6px; border:1px solid #444; background:#1a1a1a; color:#eee; }
  button { margin-top:20px; width:100%; padding:12px; font-size:16px; border-radius:6px; border:none; background:#2a6df5; color:#fff; }
  .error { color:#ff5555; margin-top:14px; }
</style>
</head>
<body>
<h1>Car Test Access</h1>
<form method="post" action="/car-test-access">
  <label for="car_id">Car</label>
  <select name="car_id" id="car_id">
    %CAR_OPTIONS%
  </select>
  <label for="password">Password</label>
  <input type="password" name="password" id="password" autofocus>
  <button type="submit">Get control link</button>
</form>
%ERROR%
</body>
</html>
"""


@router.get("/car-test-access", response_class=HTMLResponse)
def car_test_access_form(db: Session = Depends(get_session)):
    cars = db.exec(select(Car).order_by(Car.sort_order.asc())).all()
    options = "".join(f'<option value="{c.id}">{c.label}</option>' for c in cars)
    page = TEST_ACCESS_FORM.replace("%CAR_OPTIONS%", options).replace("%ERROR%", "")
    return HTMLResponse(page)


@router.post("/car-test-access")
def car_test_access_submit(
    car_id: int = Form(...), password: str = Form(...), db: Session = Depends(get_session)
):
    if password != CAR_TEST_PASSWORD:
        cars = db.exec(select(Car).order_by(Car.sort_order.asc())).all()
        options = "".join(f'<option value="{c.id}">{c.label}</option>' for c in cars)
        page = TEST_ACCESS_FORM.replace("%CAR_OPTIONS%", options).replace(
            "%ERROR%", '<p class="error">Wrong password.</p>'
        )
        return HTMLResponse(page, status_code=403)

    car = db.get(Car, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail="car not found")

    test_session = CarTestSession(car_id=car_id)
    db.add(test_session)
    db.commit()
    db.refresh(test_session)

    # Pre-warm the caches so even the FIRST /car-control page load and /drive
    # call skip the database, not just subsequent ones.
    _car_label_cache[car_id] = car.label
    _session_cache[(car_id, test_session.session_token)] = test_session.created_at

    return RedirectResponse(
        url=f"/car-control/{car_id}?session={test_session.session_token}", status_code=303
    )
