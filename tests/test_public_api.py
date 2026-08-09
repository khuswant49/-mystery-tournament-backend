from datetime import datetime, timedelta

from sqlmodel import Session, select

import app.db as db_module
from app.services import round_service


def _db():
    return Session(db_module.engine)


def test_join_without_active_round_returns_409(client):
    resp = client.post("/api/join", json={"name": "Alice"})
    assert resp.status_code == 409


def test_active_round_check_has_no_side_effects(client):
    # Polling before a round exists should never create anything.
    assert client.get("/api/rounds/active").json() == {"active": False, "round_id": None, "scenario_id": None}

    with _db() as db:
        round_service.create_round(db, "SC01")

    resp = client.get("/api/rounds/active").json()
    assert resp["active"] is True
    assert resp["scenario_id"] == "SC01"

    # Polling repeatedly (as a waiting screen would) must not create Entry rows.
    for _ in range(3):
        client.get("/api/rounds/active")
    with _db() as db:
        from app.models import Entry
        assert len(db.exec(select(Entry)).all()) == 0


def test_repeated_join_with_same_name_returns_the_same_entry(client):
    # Regression test for a real, repeatedly-reproduced bug: a client-side
    # join request that times out (Render's free tier can be slow) may have
    # already succeeded server-side, and the Ren'Py client retries on what
    # it sees as a failure -- without this, every retry created a brand new
    # Entry row, leaving duplicate "still playing" ghosts in the admin
    # dashboard for a player who actually already joined (or even already
    # won). /api/join must be idempotent per (round, name).
    with _db() as db:
        round_service.create_round(db, "SC01")

    first = client.post("/api/join", json={"name": "lana"}).json()
    second = client.post("/api/join", json={"name": "lana"}).json()
    third = client.post("/api/join", json={"name": "lana"}).json()

    assert first["entry_id"] == second["entry_id"] == third["entry_id"]

    with _db() as db:
        from app.models import Entry

        rows = db.exec(select(Entry).where(Entry.player_name == "lana")).all()
        assert len(rows) == 1


def test_repeated_join_still_returns_the_entry_after_it_already_won(client):
    # The specific scenario reported live: a player wins, is routed back
    # toward the join flow, and a retried/duplicate join call must still
    # resolve to their already-submitted, already-ranked entry -- not spawn
    # a fresh, never-submitted duplicate that sits stuck "playing..."
    # forever in the admin dashboard.
    with _db() as db:
        round_ = round_service.create_round(db, "SC01")
        entry = round_service.join_round(db, "lana")
        round_service.submit_result(db, entry, 43.9, True, 545, "true_ending")
        entry_id = entry.id

    resp = client.post("/api/join", json={"name": "lana"}).json()
    assert resp["entry_id"] == entry_id

    with _db() as db:
        from app.models import Entry

        rows = db.exec(select(Entry).where(Entry.player_name == "lana")).all()
        assert len(rows) == 1
        assert rows[0].correct is True


def test_first_correct_finisher_is_awarded_instantly_without_waiting(client):
    """The core property the whole instant-award design exists for: whoever
    submits correctly FIRST gets their rank+car immediately, while the round
    is still in_progress and nobody else has finished yet -- they never have
    to wait around for a 2nd/3rd player or a timeout."""
    with _db() as db:
        round_service.create_round(db, "SC01")

    entries = [client.post("/api/join", json={"name": n}).json()["entry_id"] for n in ["A", "B", "C", "D"]]

    # Only A has submitted so far. Note: A's elapsed_seconds is deliberately
    # the SLOWEST of the eventual finishers -- rank is arrival order now, not
    # speed, so being first to submit is what wins, not being fastest.
    resp = client.post(
        f"/api/entries/{entries[0]}/submit",
        json={"elapsed_seconds": 200.0, "correct": True, "score": 800, "ending": "true_ending"},
    )
    assert resp.status_code == 200

    # The round is NOT closed -- B, C, D haven't finished -- yet A already
    # has a rank and both QR codes, right now.
    result_a = client.get(f"/api/entries/{entries[0]}/result").json()
    assert result_a["round_status"] == "closed"  # per-entry "finalized" flag, not round-wide
    assert result_a["rank"] == 1
    assert result_a["car"] is not None
    assert "wifi_qr_png_b64" in result_a["car"]
    assert "control_qr_png_b64" in result_a["car"]

    with _db() as db:
        from app.models import Round

        live_round = db.exec(select(Round)).first()
        assert live_round.status == "in_progress"  # the round itself is still open for B/C/D

    # B still waiting -- no award yet, round still open for them too.
    result_b = client.get(f"/api/entries/{entries[1]}/result").json()
    assert result_b["round_status"] == "in_progress"
    assert result_b["rank"] is None


def test_full_round_lifecycle_ranks_by_arrival_order_not_speed(client):
    with _db() as db:
        round_ = round_service.create_round(db, "SC01")
        round_id = round_.id

    entry_ids = []
    for name in ["A", "B", "C", "D", "E", "F"]:
        resp = client.post("/api/join", json={"name": name})
        assert resp.status_code == 200
        entry_ids.append(resp.json()["entry_id"])

    # First 3 to SUBMIT finish correctly, deliberately NOT in speed order --
    # rank is decided by arrival order now, elapsed_seconds is irrelevant to
    # who gets a car (it's still recorded, just for the all-time leaderboard).
    times = [55.0, 40.0, 70.0]
    for entry_id, elapsed in zip(entry_ids[:3], times):
        resp = client.post(
            f"/api/entries/{entry_id}/submit",
            json={"elapsed_seconds": elapsed, "correct": True, "score": 800, "ending": "true_ending"},
        )
        assert resp.status_code == 200

    resp = client.get(f"/api/rounds/{round_id}/state")
    assert resp.json()["status"] == "closed"

    # entry_ids[0] submitted FIRST (even though 55s isn't the fastest time) -> rank 1
    result0 = client.get(f"/api/entries/{entry_ids[0]}/result").json()
    assert result0["rank"] == 1
    assert result0["car"] is not None
    assert "wifi_qr_png_b64" in result0["car"]
    assert "control_qr_png_b64" in result0["car"]

    # entry_ids[1] submitted 2nd -> rank 2
    assert client.get(f"/api/entries/{entry_ids[1]}/result").json()["rank"] == 2

    # entry_ids[2] submitted 3rd -> rank 3
    assert client.get(f"/api/entries/{entry_ids[2]}/result").json()["rank"] == 3

    # A player who never got to submit sees their own outcome as finalized
    # once the round closes around them, with no award.
    result3 = client.get(f"/api/entries/{entry_ids[3]}/result").json()
    assert result3["round_status"] == "closed"
    assert result3["rank"] is None
    assert result3["car"] is None

    # No more joins once the round has closed
    resp = client.post("/api/join", json={"name": "LateJoiner"})
    assert resp.status_code == 409


def test_incorrect_finish_never_qualifies_even_if_fast(client):
    with _db() as db:
        round_service.create_round(db, "SC02")

    entries = []
    for name in ["A", "B", "C", "D"]:
        entries.append(client.post("/api/join", json={"name": name}).json()["entry_id"])

    # A finishes fast but WRONG -- should never rank, even though it's the
    # quickest submission of the round.
    client.post(
        f"/api/entries/{entries[0]}/submit",
        json={"elapsed_seconds": 10.0, "correct": False, "score": 100, "ending": "wrong_ending"},
    )
    # B, C, D finish correctly and should claim ranks 1-3
    for entry_id, elapsed in zip(entries[1:], [90.0, 91.0, 92.0]):
        client.post(
            f"/api/entries/{entry_id}/submit",
            json={"elapsed_seconds": elapsed, "correct": True, "score": 500, "ending": "good_ending"},
        )

    result_a = client.get(f"/api/entries/{entries[0]}/result").json()
    assert result_a["rank"] is None
    assert result_a["car"] is None

    result_b = client.get(f"/api/entries/{entries[1]}/result").json()
    assert result_b["rank"] == 1


def test_round_closes_on_timeout_even_with_fewer_than_3_correct(client):
    with _db() as db:
        round_ = round_service.create_round(db, "SC03")
        round_.timer_limit_seconds = 0
        round_.opened_at = datetime.utcnow() - timedelta(seconds=5)
        db.add(round_)
        db.commit()

    entry_id = client.post("/api/join", json={"name": "Solo"}).json()["entry_id"]

    # Polling triggers maybe_close_round() -- should see it closed even though
    # nobody ever submitted 3 correct results.
    result = client.get(f"/api/entries/{entry_id}/result").json()
    assert result["round_status"] == "closed"
    assert result["rank"] is None


def test_car_assignment_matches_arrival_order_not_elapsed_time(client):
    with _db() as db:
        round_service.create_round(db, "SC04")

    entries = [client.post("/api/join", json={"name": n}).json()["entry_id"] for n in ["A", "B", "C"]]
    # Submitted in order A, B, C -- but A is the SLOWEST (100s) and C the
    # FASTEST (10s). If car assignment were still keyed off elapsed_seconds,
    # C would get Car 1. It shouldn't -- A submitted first, so A gets Car 1.
    for entry_id, elapsed in zip(entries, [100.0, 50.0, 10.0]):
        client.post(
            f"/api/entries/{entry_id}/submit",
            json={"elapsed_seconds": elapsed, "correct": True, "score": 900, "ending": "true_ending"},
        )

    result_a = client.get(f"/api/entries/{entries[0]}/result").json()
    assert result_a["car"]["label"] == "Car 1"
    result_c = client.get(f"/api/entries/{entries[2]}/result").json()
    assert result_c["car"]["label"] == "Car 3"
