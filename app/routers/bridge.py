"""WebSocket endpoint the admin laptop's Bluetooth bridge connects OUT to.

Players' phones reach the cloud backend over their own mobile data (not the
venue WiFi), so this backend can never reach INTO the admin's laptop -- the
laptop has to be the one holding an outbound connection instead, the
standard reverse-relay pattern for controlling a device that sits behind
NAT/a firewall/mobile hotspot with no public address of its own.

Single-bridge model: there's exactly one admin laptop physically near the
cars, so a newly-connecting bridge simply replaces whatever connection was
there before (e.g. reconnecting after a WiFi blip) rather than juggling
multiple registrations.
"""
import json
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config import CAR_ADMIN_KEY

router = APIRouter()

_bridge_ws: Optional[WebSocket] = None


def is_bridge_connected() -> bool:
    return _bridge_ws is not None


async def send_drive_to_bridge(car_label: str, left: int, right: int) -> bool:
    """Forwards a drive command to the connected bridge. Returns False if no
    bridge is currently connected (admin laptop offline/crashed/not yet
    started) so the HTTP layer can surface that distinctly from "your
    session is invalid/expired"."""
    global _bridge_ws
    if _bridge_ws is None:
        return False
    try:
        await _bridge_ws.send_text(json.dumps({"type": "drive", "car": car_label, "l": left, "r": right}))
        return True
    except Exception:
        _bridge_ws = None
        return False


@router.websocket("/bridge/ws")
async def bridge_socket(websocket: WebSocket, key: str = Query(...)):
    global _bridge_ws

    if key != CAR_ADMIN_KEY:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    _bridge_ws = websocket
    try:
        while True:
            # The bridge doesn't need to send us anything meaningful -- it just
            # sends periodic heartbeat text so we have something to await, which
            # is what lets us detect a disconnect via WebSocketDisconnect below.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if _bridge_ws is websocket:
            _bridge_ws = None
