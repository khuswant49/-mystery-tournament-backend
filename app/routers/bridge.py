"""HTTP-polling endpoint the admin laptop's Bluetooth bridge polls.

Originally built as a WebSocket (the admin laptop holding an outbound
connection to relay drive commands down to Bluetooth -- see
project_context.md's "Phase 2 architecture pivot" for the full reasoning on
why a laptop-side relay is required at all). Switched to plain HTTP polling
after live testing showed Render's free-tier service (fronted by Cloudflare)
does not pass through WebSocket upgrade handshakes at all -- confirmed with
both a raw Python client and a real browser, both failing identically
(connection reset before the handshake completes), which is a platform-level
block, not something fixable from application code. Ordinary HTTPS requests
through this same stack already work fine (every other endpoint here proves
that), so polling sidesteps the problem entirely.

Model: this module holds the LATEST desired left/right drive value per car
in memory (not a queue of every command ever sent -- only the current state
matters for continuous drive control, same as the ESP32 firmware itself only
ever tracks "what should the motors be doing right now"). The bridge polls
this every ~150-250ms and re-applies whatever it gets, for every car, every
poll -- including cars nobody's currently driving (harmless: sending "0,0"
to an already-stopped car is a no-op), which conveniently also satisfies the
firmware's own IDLE_STOP_MS safety net without any special-casing.
"""
import time
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException, Query

from app.config import CAR_ADMIN_KEY

router = APIRouter()

# car label -> (left, right) -- always the CURRENT desired state, not a queue.
_car_state: Dict[str, Tuple[int, int]] = {}

_last_poll_at: float = 0.0
_BRIDGE_STALE_SECONDS = 3.0


def is_bridge_connected() -> bool:
    return _last_poll_at > 0 and (time.time() - _last_poll_at) < _BRIDGE_STALE_SECONDS


def set_drive_state(car_label: str, left: int, right: int) -> None:
    """Called by car_control.py's /api/cars/{id}/drive -- just updates the
    latest desired state; delivery happens whenever the bridge next polls."""
    _car_state[car_label] = (left, right)


@router.get("/bridge/poll")
def bridge_poll(key: str = Query(...)):
    global _last_poll_at
    if key != CAR_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="bad key")

    _last_poll_at = time.time()
    return {"cars": {label: {"l": l, "r": r} for label, (l, r) in _car_state.items()}}
