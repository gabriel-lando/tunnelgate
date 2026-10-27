from __future__ import annotations

import secrets

import httpx2
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    APP,
    PASSWORD,
    WRONG_PASSWORD,
    FakeCloudflare,
    csrf_headers,
    password_login,
)
from tunnelgate.app import create_app
from tunnelgate.auth import LoginThrottle
from tunnelgate.config import Settings
from tunnelgate.store import Store


def _audit(client: TestClient) -> list[tuple[str, str, str]]:
    store: Store = client.app.state.store  # type: ignore[attr-defined]
    rows = store._conn.execute("SELECT actor, action, outcome FROM audit_log").fetchall()
    return [tuple(r) for r in rows]


def test_login_page_redirects_to_spa_form(password_client: TestClient) -> None:
    resp = password_client.get("/auth/login")
    assert resp.status_code == 303 and resp.headers["location"] == "/login"
    me = password_client.get("/api/me")
    assert me.status_code == 401 and me.json() == {"error": "unauthenticated", "auth": "password"}


def test_oidc_routes_do_not_exist(password_client: TestClient) -> None:
    assert password_client.get("/auth/callback").status_code == 404


def test_successful_login_creates_session(password_client: TestClient) -> None:
    resp = password_login(password_client)
    assert resp.status_code == 204, resp.text
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-tunnelgate=") and "httponly" in cookie.lower()
    me = password_client.get("/api/me").json()
    assert me["username"] == "admin" and me["groups"] == []
    assert password_client.get("/api/state").status_code == 200
    assert password_client.get("/auth/login").headers["location"] == "/"
    assert ("admin", "login", "ok") in _audit(password_client)


def test_wrong_credentials_are_rejected_and_audited(password_client: TestClient) -> None:
    for user, pw in (("admin", WRONG_PASSWORD), ("root", PASSWORD), ("admin", PASSWORD.strip())):
        resp = password_login(password_client, user, pw)
        assert resp.status_code == 401, (user, pw)
        assert "set-cookie" not in resp.headers
    assert password_client.get("/api/state").status_code == 401
    assert ("root", "login", "denied") in _audit(password_client)


def test_login_requires_same_origin(password_client: TestClient) -> None:
    body = {"username": "admin", "password": PASSWORD}
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
        resp = password_client.post("/auth/login", json=body, headers=headers)
        assert resp.status_code == 403, headers
    assert password_client.get("/api/me").status_code == 401


def test_login_rejects_bad_bodies(password_client: TestClient) -> None:
    for body in (
        {"username": "admin"},
        {"username": "", "password": WRONG_PASSWORD},
        {"username": "admin", "password": WRONG_PASSWORD, "extra": 1},
        {"username": "a" * 200, "password": WRONG_PASSWORD},
    ):
        resp = password_client.post("/auth/login", json=body, headers={"Origin": APP})
        assert resp.status_code == 422, body


def test_repeated_failures_are_throttled(password_client: TestClient) -> None:
    for _ in range(LoginThrottle.free_failures):
        assert password_login(password_client, password=WRONG_PASSWORD).status_code == 401
    resp = password_login(password_client)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    for _ in range(50):
        assert password_login(password_client, "x" * 128).status_code == 429
    throttled = [row for row in _audit(password_client) if row[2] == "throttled"]
    assert throttled == [("admin", "login", "throttled")]


def test_throttle_survives_long_attacks(
    monkeypatch: pytest.MonkeyPatch, password_settings: Settings, fake_cf: FakeCloudflare
) -> None:
    original = LoginThrottle.__init__

    def init(self: LoginThrottle) -> None:
        original(self)
        self.failures = 1028

    monkeypatch.setattr(LoginThrottle, "__init__", init)
    app = create_app(password_settings, cf_transport=httpx2.MockTransport(fake_cf.handler))
    with TestClient(app, base_url=APP, raise_server_exceptions=False) as c:
        assert password_login(c, password=WRONG_PASSWORD).status_code == 401
        for _ in range(5):
            assert password_login(c, password=WRONG_PASSWORD).status_code == 429
        assert password_login(c).status_code == 429


def test_throttle_backoff_and_reset() -> None:
    t = LoginThrottle()
    for _ in range(4):
        t.failed(100.0)
    assert t.retry_after(100.0) == 0
    t.failed(100.0)
    assert t.retry_after(100.0) == 1
    for _ in range(20):
        t.failed(100.0)
    assert t.retry_after(100.0) == LoginThrottle.max_delay
    assert t.retry_after(100.0 + LoginThrottle.max_delay) == 0
    t.succeeded()
    assert t.failures == 0 and t.retry_after(100.0) == 0
    t.failures = 5000
    t.failed(100.0)
    assert t.retry_after(100.0) == LoginThrottle.max_delay
    assert t.first_rejection() and not t.first_rejection()
    t.failed(200.0)
    assert t.first_rejection()


def test_api_mutations_still_need_csrf(password_client: TestClient) -> None:
    password_login(password_client)
    body = {"hostname": "jellyfin.example.com", "blocked": True}
    assert (
        password_client.post("/api/routes/block", json=body, headers={"Origin": APP}).status_code
        == 403
    )
    ok = password_client.post("/api/routes/block", json=body, headers=csrf_headers(password_client))
    assert ok.status_code == 200, ok.text


def test_logout_invalidates_copied_cookie(password_client: TestClient) -> None:
    password_login(password_client)
    stolen = dict(password_client.cookies)
    resp = password_client.post("/auth/logout", headers={"Origin": APP})
    assert resp.status_code == 303 and resp.headers["location"] == "/signed-out"
    password_client.cookies.clear()
    password_client.cookies.update(stolen)
    assert password_client.get("/api/state").status_code == 401


def test_logout_then_login_and_origin_check(password_client: TestClient) -> None:
    password_login(password_client)
    assert password_client.post("/auth/logout").status_code == 403
    resp = password_client.post("/auth/logout?then=login", headers={"Origin": APP})
    assert resp.headers["location"] == "/login"


def test_session_fixation_is_prevented(password_client: TestClient) -> None:
    password_login(password_client)
    first = password_client.get("/api/me").json()["csrf_token"]
    password_login(password_client)
    assert password_client.get("/api/me").json()["csrf_token"] != first


def test_csp_has_no_identity_provider(password_client: TestClient) -> None:
    csp = password_client.get("/").headers["content-security-policy"]
    assert "form-action 'self';" in csp + ";"


@pytest.mark.usefixtures("password_settings")
def test_plain_password_mode(monkeypatch: pytest.MonkeyPatch, fake_cf: FakeCloudflare) -> None:
    plain = secrets.token_urlsafe(12)
    monkeypatch.delenv("BASIC_AUTH_PASSWORD_HASH")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", plain)
    app = create_app(Settings(), cf_transport=httpx2.MockTransport(fake_cf.handler))
    with TestClient(app, base_url=APP, follow_redirects=False) as c:
        assert password_login(c, password=PASSWORD).status_code == 401
        assert password_login(c, password=plain).status_code == 204
