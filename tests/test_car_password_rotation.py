from sqlmodel import Session, select

import app.db as db_module
from app.models import Car
from app.services import round_service


def _db():
    return Session(db_module.engine)


def test_starting_a_round_gives_every_car_a_fresh_password(client):
    with _db() as db:
        before = {c.id: c.wifi_password for c in db.exec(select(Car)).all()}
    assert len(before) == 3  # _seed_cars() fixture

    client.post("/admin/login", data={"pin": "test-pin"})
    client.post("/admin/rounds", data={"scenario_id": "SC01"})

    with _db() as db:
        after = {c.id: c.wifi_password for c in db.exec(select(Car)).all()}

    # Every car's password actually changed, and none of them collide.
    for car_id, old_password in before.items():
        assert after[car_id] != old_password
    assert len(set(after.values())) == 3


def test_generated_car_passwords_are_wifi_safe_length():
    # Real WiFi passwords need to be at least 8 characters; also checking
    # they avoid visually-ambiguous characters (0/O, 1/l/I) since the admin
    # reads these off a screen and types/scans them standing next to a car.
    for _ in range(50):
        pw = round_service._generate_car_password()
        assert len(pw) >= 8
        assert not any(c in pw for c in "0O1lI")


def test_round_detail_page_shows_a_sync_link_per_car(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    start_resp = client.post("/admin/rounds", data={"scenario_id": "SC01"}, follow_redirects=False)
    round_url = start_resp.headers["location"]

    resp = client.get(round_url)
    assert resp.status_code == 200
    assert "Sync Car WiFi Passwords" in resp.text
    assert resp.text.count("Push link") == 3


def test_starting_a_round_redirects_straight_to_its_own_detail_page(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.post("/admin/rounds", data={"scenario_id": "SC01"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/rounds/")
    assert resp.headers["location"] != "/admin/"
