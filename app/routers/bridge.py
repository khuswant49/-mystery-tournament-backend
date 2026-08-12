"""WebSocket endpoint the admin laptop's Bluetooth bridge connects OUT to.

Players' phones reach the backend over their own mobile data (not the
venue WiFi), so this backend can never reach INTO the admin's laptop -- the
laptop has to be the one holding an outbound connection instead, the
standard reverse-relay pattern for controlling a device that sits behind
NAT/a firewall/mobile hotspot with no public address of its own.

This was a WebSocket originally, got switched to HTTP polling after live
testing showed Render's free-tier service (fronted by Cloudflare) silently
drops WebSocket upgrades -- confirmed with both a raw Python client and a
real browser, both failing identically before the handshake completed. That
diagnosis held for Render specifically, but this project has since moved
its actual live traffic off Render entirely (Render is now just a thin
bootstrap redirect -- see project_context.md's "Self-hosted backend +
Cloudflare Tunnel" section) onto a self-hosted backend reached through a
genuine Cloudflare Tunnel (the `cloudflared` client, a different product
from "a Render app that happens to be proxied by Cloudflare's CDN"). Tested
directly with an isolated echo server before reverting: WebSockets pass
through a real Cloudflare Tunnel cleanly. Switched back to a WebSocket push
here because it removes the polling interval's inherent latency floor
entirely (the bridge no longer waits up to one poll cycle to learn about a
new command -- it's pushed the instant it's issued), which mattered because
the polling version was still measurably laggier than players wanted even
after the Render migration fixed the dominant bottleneck.

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
