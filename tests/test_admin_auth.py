def test_unauthenticated_admin_page_redirects_to_login(client):
    # A human hitting /admin/ directly (bookmark, typed URL) without a session
    # cookie should land on the login page, not see a bare JSON error.
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_unauthenticated_api_call_still_gets_plain_json(client):
    # The redirect behavior is admin-HTML-only -- game-facing /api/* clients
    # must keep getting normal JSON error responses, never a redirect.
    resp = client.post("/api/join", json={"name": "Test"}, follow_redirects=False)
    assert resp.status_code == 409
    assert resp.json() == {"detail": "no active round"}


def test_login_then_admin_page_succeeds(client):
    login = client.post("/admin/login", data={"pin": "test-pin"}, follow_redirects=False)
    assert login.status_code == 303
    assert "mt_admin_session" in login.cookies

    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Rounds" in resp.text or "Start a Round" in resp.text


def test_wrong_pin_does_not_redirect_or_set_cookie(client):
    resp = client.post("/admin/login", data={"pin": "wrong"}, follow_redirects=False)
    assert resp.status_code == 401
    assert "mt_admin_session" not in resp.cookies


def test_force_close_button_actually_closes_the_round(client):
    # Regression test for a live report of "Force Close doesn't work" -- this
    # confirms the server-side endpoint itself is not the problem (it wasn't;
    # the browser's confirm() dialog was almost certainly getting dismissed).
    client.post("/admin/login", data={"pin": "test-pin"})

    from app.services import round_service
    import app.db as db_module
    from sqlmodel import Session

    with Session(db_module.engine) as db:
        round_ = round_service.create_round(db, "SC01")
        round_id = round_.id

    resp = client.post(f"/admin/rounds/{round_id}/force_close", follow_redirects=False)
    assert resp.status_code == 303

    active = client.get("/api/rounds/active").json()
    assert active["active"] is False
