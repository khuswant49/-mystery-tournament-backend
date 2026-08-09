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

    bootstrap = client.get("/api/backend_mode").json()
    assert bootstrap == {"mode": "lan", "lan_api_base": "http://192.168.1.50:8000"}


def test_admin_can_switch_back_to_cloud(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    client.post("/admin/backend-mode", data={"mode": "lan", "lan_api_base": "http://192.168.1.50:8000"})
    client.post("/admin/backend-mode", data={"mode": "cloud", "lan_api_base": ""})

    assert client.get("/api/backend_mode").json() == {"mode": "cloud", "lan_api_base": None}


def test_switching_to_lan_without_an_ip_is_rejected(client):
    client.post("/admin/login", data={"pin": "test-pin"})
    resp = client.post("/admin/backend-mode", data={"mode": "lan", "lan_api_base": ""})
    assert resp.status_code == 400
    # Rejected update must not have taken effect.
    assert client.get("/api/backend_mode").json()["mode"] == "cloud"
