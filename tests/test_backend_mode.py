def test_defaults_to_cloud_mode_with_no_admin_action(client):
    # A brand-new deployment (nobody has touched the Backend Mode page yet)
    # must still answer sensibly -- game clients bootstrap against this on
    # launch, before any admin has necessarily logged in.
    resp = client.get("/api/backend_mode")
    assert resp.status_code == 200
    assert resp.json() == {"mode": "cloud", "lan_api_base": None}


def test_unauthenticated_request_cannot_change_mode(client):
    resp = client.post(
        "/admin/backend-mode",
        data={"mode": "lan", "lan_api_base": "http://192.168.1.50:8000"},
        follow_redirects=False,
    )
    assert resp.status_code in (401, 303)
    # Either way, the public bootstrap endpoint must not reflect the change.
    assert client.get("/api/backend_mode").json()["mode"] == "cloud"


def test_admin_can_switch_to_lan_and_public_endpoint_reflects_it(client):
    client.post("/admin/login", data={"pin": "test-pin"})

    resp = client.post(
        "/admin/backend-mode",
        data={"mode": "lan", "lan_api_base": "http://192.168.1.50:8000"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Switching to LAN must send the admin's own browser to that LAN
    # server's dashboard, not this one -- this instance's own view of
    # rounds/players is a separate database from whatever game clients are
    # now using.
    assert resp.headers["location"] == "http://192.168.1.50:8000/admin/backend-mode"

    bootstrap = client.get("/api/backend_mode").json()
    assert bootstrap == {"mode": "lan", "lan_api_base": "http://192.168.1.50:8000"}


def test_admin_can_switch_back_to_cloud(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    client.post(
        "/admin/backend-mode",
        data={"mode": "lan", "lan_api_base": "http://192.168.1.50:8000"},
        follow_redirects=False,
    )
    resp = client.post(
        "/admin/backend-mode", data={"mode": "cloud", "lan_api_base": ""}, follow_redirects=False
    )
    assert resp.status_code == 303
    # Switching back to cloud must send the admin back to the one canonical,
    # well-known cloud dashboard -- not wherever they happen to be standing.
    # (CANONICAL_CLOUD_ADMIN_URL is overridden in tests -- see conftest.py.)
    assert resp.headers["location"] == "http://testserver/admin/backend-mode"

    assert client.get("/api/backend_mode").json() == {"mode": "cloud", "lan_api_base": None}


def test_switching_to_lan_without_an_ip_is_rejected(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.post("/admin/backend-mode", data={"mode": "lan", "lan_api_base": ""})
    assert resp.status_code == 400
    # Rejected update must not have taken effect.
    assert client.get("/api/backend_mode").json()["mode"] == "cloud"


def test_switching_to_lan_without_a_scheme_is_rejected(client):
    # A bare IP with no http:// would produce a broken/ambiguous redirect
    # target for both the admin's own browser and every game client.
    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.post("/admin/backend-mode", data={"mode": "lan", "lan_api_base": "192.168.1.50:8000"})
    assert resp.status_code == 400
    assert client.get("/api/backend_mode").json()["mode"] == "cloud"


def test_unauthenticated_cannot_probe_detected_ip(client):
    resp = client.get("/admin/api/detected-lan-ip", follow_redirects=False)
    assert resp.status_code in (401, 303)


def test_detected_ip_endpoint_returns_a_usable_url(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.get("/admin/api/detected-lan-ip")
    assert resp.status_code == 200
    data = resp.json()
    assert "ip" in data and "suggested_url" in data
    assert data["suggested_url"].startswith("http://")
    assert data["ip"] in data["suggested_url"]


def test_canonical_instance_shows_the_mode_toggle_form(client):
    # The test client's own request base_url ("http://testserver") matches
    # CANONICAL_CLOUD_ADMIN_URL (overridden in conftest.py) -- this IS the
    # canonical deployment from the page's point of view, so it should
    # render the real editable toggle.
    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.get("/admin/backend-mode")
    assert resp.status_code == 200
    assert 'name="mode"' in resp.text
    assert "Detect this machine's IP" in resp.text
    assert "This is a LAN server instance" not in resp.text


def test_non_canonical_instance_reports_itself_active_when_cloud_agrees(client, monkeypatch):
    # Regression test: an admin on the actual LAN server that's genuinely
    # serving players was seeing this page report its own (unused) local
    # "cloud" row and reasonably reading that as "not active" -- even
    # though the real, canonical cloud deployment was pointing everyone at
    # it. The page must instead show a live comparison against the
    # canonical source, not its own meaningless local setting.
    import httpx

    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router, "CANONICAL_CLOUD_ADMIN_URL", "https://example-cloud.invalid")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"mode": "lan", "lan_api_base": "http://testserver"}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse())

    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.get("/admin/backend-mode")
    assert resp.status_code == 200
    assert "This is a LAN server instance" in resp.text
    assert "ACTIVE" in resp.text
    assert "NOT ACTIVE" not in resp.text
    # No pointless toggle for a setting that isn't actually consulted here.
    assert 'name="mode"' not in resp.text


def test_non_canonical_instance_flags_when_cloud_points_elsewhere(client, monkeypatch):
    import httpx

    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router, "CANONICAL_CLOUD_ADMIN_URL", "https://example-cloud.invalid")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"mode": "lan", "lan_api_base": "http://someone-elses-laptop:8000"}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse())

    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.get("/admin/backend-mode")
    assert resp.status_code == 200
    assert "NOT ACTIVE" in resp.text


def test_non_canonical_instance_handles_unreachable_cloud_gracefully(client, monkeypatch):
    import httpx

    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router, "CANONICAL_CLOUD_ADMIN_URL", "https://example-cloud.invalid")

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "get", _raise)

    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.get("/admin/backend-mode")
    assert resp.status_code == 200
    assert "UNKNOWN" in resp.text
