from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.conftest import APP, ISSUER, FakeOidc, csrf_headers, login


def test_unauthenticated_api_returns_401(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/state").status_code == 401


def test_login_redirect_uses_pkce_state_and_nonce(client: TestClient) -> None:
    resp = client.get("/auth/login")
    assert resp.status_code in (302, 303, 307)
    url = urlsplit(resp.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/api/oidc/authorization"
    q = parse_qs(url.query)
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == [f"{APP}/auth/callback"]
    assert q["state"] and q["nonce"] and q["code_challenge"]
    assert "groups" in q["scope"][0]


def test_successful_login_sets_hardened_cookie(client: TestClient, oidc: FakeOidc) -> None:
    resp = login(client, oidc)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-tunnelgate=")
    assert "secure" in cookie.lower() and "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    me = client.get("/api/me").json()
    assert me["username"] == "gabriel"
    assert me["groups"] == ["Users", "HomeAdmins"]
    assert len(me["csrf_token"]) > 30


def test_group_check_is_case_insensitive(client: TestClient, oidc: FakeOidc) -> None:
    oidc.userinfo["groups"] = ["homeadmins"]
    assert login(client, oidc).headers["location"] == "/"


@pytest.mark.parametrize(
    ("userinfo_groups", "amr", "reason"),
    [
        (["Users"], ["pwd", "otp", "mfa"], "group"),
        (["HomeAdmins"], ["pwd"], "mfa"),
        (["HomeAdmins"], None, "mfa"),
    ],
)
def test_authenticated_but_unauthorized_gets_denied_page_without_loop(
    client: TestClient,
    oidc: FakeOidc,
    userinfo_groups: list[str],
    amr: list[str] | None,
    reason: str,
) -> None:
    oidc.userinfo["groups"] = userinfo_groups
    oidc.claims["amr"] = amr
    resp = login(client, oidc)
    assert resp.headers["location"] == "/denied"
    me = client.get("/api/me")
    assert me.status_code == 403
    assert me.json() == {"error": "forbidden", "reason": reason, "username": "gabriel"}
    assert client.get("/api/state").status_code == 403
    page = client.get("/denied")
    assert page.status_code == 200 and "spa" in page.text


def test_possession_factor_without_mfa_label_is_accepted(
    client: TestClient, oidc: FakeOidc
) -> None:
    oidc.claims["amr"] = ["pwd", "hwk"]
    assert login(client, oidc).headers["location"] == "/"


def test_wrong_audience_is_rejected(client: TestClient, oidc: FakeOidc) -> None:
    oidc.claims["aud"] = "someone-else"
    resp = login(client, oidc)
    assert resp.status_code == 400
    assert client.get("/api/me").status_code == 401


def test_wrong_issuer_is_rejected(client: TestClient, oidc: FakeOidc) -> None:
    oidc.claims["iss"] = "https://evil.example.com"
    assert login(client, oidc).status_code == 400


def test_userinfo_subject_mismatch_is_rejected(client: TestClient, oidc: FakeOidc) -> None:
    oidc.userinfo["sub"] = "someone-else"
    assert login(client, oidc).status_code == 400
    assert client.get("/api/me").status_code == 401


def test_callback_with_forged_state_fails(client: TestClient) -> None:
    client.get("/auth/login")
    resp = client.get("/auth/callback", params={"code": "abc", "state": "forged"})
    assert resp.status_code == 400


def test_logout_requires_same_origin(client: TestClient, oidc: FakeOidc) -> None:
    login(client, oidc)
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"Origin": "https://evil.test"}).status_code == 403
    resp = client.post("/auth/logout", headers={"Origin": APP})
    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"{ISSUER}/logout?rd=")
    assert "signed-out" in resp.headers["location"]
    assert client.get("/api/me").status_code == 401


def test_logout_then_login_returns_to_app_root(client: TestClient, oidc: FakeOidc) -> None:
    oidc.end_session = True
    login(client, oidc)
    resp = client.post("/auth/logout?then=login", headers={"Origin": APP})
    assert resp.headers["location"].startswith(f"{ISSUER}/api/oidc/end-session?")
    assert (
        "post_logout_redirect_uri=https%3A%2F%2Ftunnelgate.int.example.com%2F"
        in (resp.headers["location"])
    )


def test_denied_user_can_log_out(client: TestClient, oidc: FakeOidc) -> None:
    oidc.userinfo["groups"] = ["Users"]
    login(client, oidc)
    resp = client.post("/auth/logout", headers={"Origin": APP})
    assert resp.status_code == 303
    assert client.get("/api/me").status_code == 401


def test_login_when_already_signed_in_goes_home(client: TestClient, oidc: FakeOidc) -> None:
    login(client, oidc)
    assert client.get("/auth/login").headers["location"] == "/"


def test_tampered_session_cookie_is_ignored(client: TestClient, oidc: FakeOidc) -> None:
    login(client, oidc)
    value = client.cookies.get("__Host-tunnelgate")
    assert value
    client.cookies.set(
        "__Host-tunnelgate", value[:-4] + "AAAA", domain="tunnelgate.int.example.com"
    )
    assert client.get("/api/me").status_code == 401


def test_expired_session_is_cleared(
    client: TestClient, oidc: FakeOidc, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, oidc)
    headers = csrf_headers(client)
    import time as _time

    real = _time.time
    monkeypatch.setattr("tunnelgate.auth.time.time", lambda: real() + 9 * 3600)
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/kill-all", json={"confirm": True}, headers=headers).status_code == 401


def test_copied_cookie_is_rejected_after_logout(client: TestClient, oidc: FakeOidc) -> None:
    login(client, oidc)
    cookie = client.cookies.get("__Host-tunnelgate")
    assert cookie
    client.post("/auth/logout", headers={"Origin": APP})
    client.cookies.set("__Host-tunnelgate", cookie, domain="tunnelgate.int.example.com")
    assert client.get("/api/me").status_code == 401


def test_login_reports_idp_outage(client: TestClient, oidc: FakeOidc) -> None:
    oidc.discovery_down = True
    assert client.get("/auth/login").status_code == 503


def test_stale_authentication_is_rejected(client: TestClient, oidc: FakeOidc) -> None:
    import time as _t

    oidc.claims["auth_time"] = int(_t.time()) - 9 * 3600
    assert login(client, oidc).status_code == 400


def test_login_requests_max_age(client: TestClient) -> None:
    q = parse_qs(urlsplit(client.get("/auth/login").headers["location"]).query)
    assert q["max_age"] == ["28800"]
