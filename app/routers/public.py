from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.config import CANONICAL_CLOUD_ADMIN_URL
from app.db import get_session
from app.models import BackendMode, Entry, LobbyPresence, QrAward, Round, Car
from app.schemas import (
    ActiveRoundResponse,
    BackendModeResponse,
    CarAward,
    EntryResultResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    JoinRequest,
    JoinResponse,
    RoundStateResponse,
    SubmitRequest,
    SubmitResponse,
)
from app.services import round_service

router = APIRouter(prefix="/api")

# A prune, not a "counts as waiting" cutoff -- see admin.py for the actual
# staleness threshold used to decide who's shown as currently in the lobby.
_HEARTBEAT_PRUNE_AGE = timedelta(hours=1)


@router.get("/rounds/active", response_model=ActiveRoundResponse)
def active_round(db: Session = Depends(get_session)):
    """Side-effect-free check for the join-waiting screen -- unlike /join, this
    never creates an Entry, so it's safe to poll repeatedly while waiting for
    the admin to start a round."""
    round_ = round_service.get_active_round(db)
    if round_ is None:
        return ActiveRoundResponse(active=False)
    return ActiveRoundResponse(active=True, round_id=round_.id, scenario_id=round_.scenario_id)


@router.get("/backend_mode", response_model=BackendModeResponse)
def backend_mode(db: Session = Depends(get_session)):
    """Bootstrap check every game client makes against this stable cloud
    deployment before doing anything else, so the admin can redirect
    everyone to a LAN host for the day (venue internet down, etc.) via a
    single dashboard toggle instead of rebuilding/redistributing the game.
    Deliberately unauthenticated -- a game client has no admin session at
    this point, and there's nothing sensitive in a LAN IP address. If
    reaching THIS endpoint itself fails (no internet at all), the client
    falls back to whatever's hardcoded locally in cloud_client.rpy."""
    row = db.get(BackendMode, 1)
    if row is None:
        return BackendModeResponse(mode="cloud", lan_api_base=None)
    return BackendModeResponse(mode=row.mode, lan_api_base=row.lan_api_base or None)


@router.post("/lobby/heartbeat", response_model=HeartbeatResponse)
def lobby_heartbeat(payload: HeartbeatRequest, db: Session = Depends(get_session)):
    """Called once per poll tick by the join-waiting screen, purely so the
    admin dashboard can show who's actually sitting in the lobby before a
    round exists to /join into. Upsert-by-name; not an authoritative record
    of anything, just a presence display."""
    name = payload.name.strip()
    if not name:
        return HeartbeatResponse()

    existing = db.get(LobbyPresence, name)
    if existing is None:
        db.add(LobbyPresence(player_name=name))
    else:
        existing.last_seen = datetime.utcnow()
        db.add(existing)
    db.commit()

    # Cheap incremental cleanup -- no separate cron/task needed for a table
    # this small.
    cutoff = datetime.utcnow() - _HEARTBEAT_PRUNE_AGE
    stale = db.exec(select(LobbyPresence).where(LobbyPresence.last_seen < cutoff)).all()
    for row in stale:
        db.delete(row)
    if stale:
        db.commit()

    return HeartbeatResponse()


@router.post("/join", response_model=JoinResponse)
def join(payload: JoinRequest, db: Session = Depends(get_session)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")

    try:
        entry = round_service.join_round(db, name)
    except round_service.NoActiveRoundError:
        raise HTTPException(status_code=409, detail="no active round")

    round_ = db.get(Round, entry.round_id)
    return JoinResponse(
        entry_id=entry.id, round_id=round_.id, scenario_id=round_.scenario_id, status=round_.status
    )


@router.get("/rounds/{round_id}/state", response_model=RoundStateResponse)
def round_state(round_id: str, db: Session = Depends(get_session)):
    round_ = db.get(Round, round_id)
    if round_ is None:
        raise HTTPException(status_code=404, detail="round not found")

    return RoundStateResponse(
        round_id=round_.id,
        scenario_id=round_.scenario_id,
        status=round_.status,
        opened_at=round_.opened_at.isoformat() if round_.opened_at else None,
    )


@router.post("/entries/{entry_id}/submit", response_model=SubmitResponse)
def submit(entry_id: str, payload: SubmitRequest, db: Session = Depends(get_session)):
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")

    round_service.submit_result(
        db, entry, payload.elapsed_seconds, payload.correct, payload.score, payload.ending
    )
    return SubmitResponse()


@router.get("/entries/{entry_id}/result", response_model=EntryResultResponse)
def entry_result(entry_id: str, db: Session = Depends(get_session)):
    """Polled by the closure-wait screen. Deliberately answers per-ENTRY, not
    per-ROUND: a qualifying player's award is created synchronously inside
    submit_result() the instant they qualify (see round_service.py), so it
    can -- and must -- show up here right away, without waiting for the
    round as a whole to close around the other 5 players. "round_status":
    "closed" in this response means "this player's own outcome is final,"
    not literally "the round is closed" -- those are two different things
    now that awarding is instant and per-player.
    """
    entry = db.get(Entry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")

    round_ = db.get(Round, entry.round_id)
    # Timeout safety net -- lets a still-in-progress round finalize on its
    # own for the entries that were never going to qualify.
    round_ = round_service.maybe_close_round(db, round_)

    award = db.exec(select(QrAward).where(QrAward.entry_id == entry_id)).first()
    if award is not None:
        car = db.get(Car, award.car_id)
        return EntryResultResponse(
            round_status="closed",
            rank=award.rank,
            car=CarAward(
                label=car.label,
                # Matches qr_service.award_entry()'s control_png_b64 exactly --
                # always the public cloud URL (players drive over mobile data,
                # not car.control_url, which is the retired WiFi-AP address).
                control_url=f"{CANONICAL_CLOUD_ADMIN_URL}/car-control/{car.id}",
                wifi_qr_png_b64=award.wifi_png_b64,
                control_qr_png_b64=award.control_png_b64,
            ),
        )

    # No award. This player's own path is finalized -- stop making them
    # wait -- once either they've submitted something that can never be
    # awarded (wrong/timeout, so no more chance), or the round itself has
    # closed around them (all 3 slots went to others, or the timer ran out
    # before they ever finished).
    if round_.status == "closed" or (entry.submitted_at is not None and not entry.correct):
        return EntryResultResponse(round_status="closed", rank=None, car=None)

    return EntryResultResponse(round_status=round_.status, rank=None, car=None)
