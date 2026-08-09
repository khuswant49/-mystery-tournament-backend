from sqlmodel import Session, select

import app.db as db_module
from app.models import LobbyPresence


def _db():
    return Session(db_module.engine)


def test_heartbeat_upserts_by_name(client):
    resp = client.post("/api/lobby/heartbeat", json={"name": "Alice"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    with _db() as db:
        rows = db.exec(select(LobbyPresence)).all()
        assert len(rows) == 1
        assert rows[0].player_name == "Alice"
        first_seen = rows[0].last_seen

    # A second heartbeat from the same name updates the row, doesn't add one.
    client.post("/api/lobby/heartbeat", json={"name": "Alice"})
    with _db() as db:
        rows = db.exec(select(LobbyPresence)).all()
        assert len(rows) == 1
        assert rows[0].last_seen >= first_seen


def test_heartbeat_ignores_blank_name(client):
    client.post("/api/lobby/heartbeat", json={"name": "   "})
    with _db() as db:
        assert db.exec(select(LobbyPresence)).all() == []


def test_admin_rounds_page_shows_waiting_players(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    client.post("/api/lobby/heartbeat", json={"name": "Bob"})

    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Bob" in resp.text
    assert "Waiting in Lobby (1)" in resp.text
