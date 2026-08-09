import secrets
import string
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.config import DEFAULT_ROUND_TIMER_SECONDS, QUALIFYING_SLOTS
from app.models import Car, Entry, Round
from app.services import qr_service


class NoActiveRoundError(Exception):
    pass


def get_active_round(db: Session) -> Optional[Round]:
    return db.exec(
        select(Round).where(Round.status.in_(["pending", "in_progress"])).order_by(Round.created_at.desc())
    ).first()


# Excludes visually-ambiguous characters (0/O, 1/l/I) since the admin has to
# read this off a screen and type/scan it while standing next to a car.
_PASSWORD_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def _generate_car_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(10))


def _rotate_car_passwords(db: Session) -> None:
    """A fresh WiFi password per car, every round -- so a QR/password handed
    out in an earlier round can't still get someone onto a car's network
    later. The physical ESP32 doesn't learn this on its own (it's an
    isolated AP with no path back to this server); the admin's own device
    has to push it to each car directly (see /admin/cars' "push" link/QR
    and esp32_car_wifi/car*/car*.ino's handleSetPassword) -- this just
    updates what the backend expects to be current, which is also what the
    next QrAward's WiFi QR code will encode.
    """
    cars = db.exec(select(Car)).all()
    for car in cars:
        car.wifi_password = _generate_car_password()
        car.updated_at = datetime.utcnow()
        db.add(car)
    db.commit()


def create_round(db: Session, scenario_id: str) -> Round:
    """Creates and immediately starts a round. Refuses to start a second one
    while another is still open -- the admin dashboard should close/force-close
    the current round first."""
    existing = get_active_round(db)
    if existing:
        return existing

    _rotate_car_passwords(db)

    round_ = Round(
        scenario_id=scenario_id,
        status="in_progress",
        timer_limit_seconds=DEFAULT_ROUND_TIMER_SECONDS,
        opened_at=datetime.utcnow(),
    )
    db.add(round_)
    db.commit()
    db.refresh(round_)
    return round_


def join_round(db: Session, player_name: str) -> Entry:
    """Idempotent by (round, player_name): repeated calls for a name that
    already has an entry in the currently active round just return that
    same entry instead of creating another one. This is the real fix for a
    duplicate-entry bug seen repeatedly in live testing -- a client-side
    join request that times out (Render's free tier can be slow) may have
    already succeeded server-side; the Ren'Py client's own retry-on-failure
    logic can't tell the difference and would otherwise create a second
    entry every time it retries. Also covers a player accidentally getting
    routed back through the join flow a second time for a round they
    already have an outcome in (e.g. after winning). Names aren't a real
    identity system here (no accounts), so two genuinely different players
    who happen to type the identical name in the same round would collide
    -- an accepted tradeoff for a low-stakes, in-person event where that's
    rare and easy to work around (ask one of them to add a number), versus
    the alternative of a reliably-reproducible duplicate-entry bug.
    """
    round_ = get_active_round(db)
    if round_ is None:
        raise NoActiveRoundError()

    existing = db.exec(
        select(Entry).where(Entry.round_id == round_.id, Entry.player_name == player_name)
    ).first()
    if existing is not None:
        return existing

    entry = Entry(round_id=round_.id, player_name=player_name)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _is_timed_out(round_: Round) -> bool:
    if round_.opened_at is None:
        return False
    elapsed = (datetime.utcnow() - round_.opened_at).total_seconds()
    return elapsed >= round_.timer_limit_seconds


def _mark_closed(db: Session, round_: Round) -> Round:
    round_.status = "closed"
    round_.closed_at = datetime.utcnow()
    db.add(round_)
    db.commit()
    db.refresh(round_)
    return round_


def maybe_close_round(db: Session, round_: Round) -> Round:
    """Timeout-only safety net now -- the normal "3 winners decided" case is
    handled instantly per-submission in submit_result() below, not here. This
    still needs to exist for the case where FEWER than 3 players ever finish
    correctly: eventually the round's own timer runs out and it closes so the
    admin can start the next one. Also double-checks the award count as a
    belt-and-suspenders close, in case submit_result()'s own close (when the
    3rd award is granted) didn't fire for some reason.
    """
    if round_.status != "in_progress":
        return round_

    if qr_service.award_count(db, round_.id) >= QUALIFYING_SLOTS or _is_timed_out(round_):
        return _mark_closed(db, round_)

    return round_


def submit_result(
    db: Session, entry: Entry, elapsed_seconds: float, correct: bool, score: int, ending: str
) -> Round:
    entry.submitted_at = datetime.utcnow()
    entry.elapsed_seconds = elapsed_seconds
    entry.correct = correct
    entry.score = score
    entry.ending = ending
    db.add(entry)
    db.commit()
    db.refresh(entry)

    round_ = db.get(Round, entry.round_id)

    # INSTANT AWARD: if this submission is correct and a car slot is still
    # open, award it right now, first-come-first-served by arrival order --
    # this player does not wait for anyone else to finish. If that was the
    # last of the 3 slots, the round closes immediately too (no more slots
    # to hand out; other players can still finish for their own score, they
    # just won't get a car).
    if correct and round_.status == "in_progress":
        current_count = qr_service.award_count(db, round_.id)
        if current_count < QUALIFYING_SLOTS:
            qr_service.award_entry(db, round_.id, entry.id, rank=current_count + 1)
            current_count += 1
            if current_count >= QUALIFYING_SLOTS:
                round_ = _mark_closed(db, round_)

    return maybe_close_round(db, round_)


def force_close_round(db: Session, round_: Round) -> Round:
    """Admin-triggered override/fallback -- not the primary path (see
    maybe_close_round / submit_result's instant-award close), but useful for
    testing or an edge case (e.g. fewer than 3 players ever correctly finish
    and the admin doesn't want to wait out the full timer)."""
    if round_.status == "closed":
        return round_
    return _mark_closed(db, round_)
