from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    APP,
    INLINE_SCRIPT,
    T_APPS,
    T_LOCAL,
    T_MEDIA,
    ZONE_ID,
    FakeCloudflare,
    fail,
)


def _state(client: TestClient) -> dict:
    resp = client.get("/api/state", params={"refresh": "true"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _route(state: dict, host: str) -> dict:
    for t in state["tunnels"]:
        for r in t["routes"]:
            if r["hostname"] == host:
                return r
    raise AssertionError(host)


def test_state_groups_routes_by_tunnel(client: TestClient, authed: dict[str, str]) -> None:
    state = _state(client)
    names = [t["name"] for t in state["tunnels"]]
    assert names == ["apps", "auth", "media"]
    apps = next(t for t in state["tunnels"] if t["id"] == T_APPS)
    assert apps["status"] == "healthy" and apps["connections"] == 8 and apps["remote_managed"]
    assert apps["replicas"] == 2 and apps["versions"] == ["2026.10.0", "2026.9.1"]
    media = next(t for t in state["tunnels"] if t["id"] == T_MEDIA)
    assert media["replicas"] == 0 and media["versions"] == []
    hosts = [r["hostname"] for r in apps["routes"]]
    assert hosts == [
        "git.example.com",
        "vault.example.com",
        "*.apps.example.com",
        "other.elsewhere.org",
    ]
    local = next(t for t in state["tunnels"] if t["id"] == T_LOCAL)
    assert not local["remote_managed"]
    assert [r["hostname"] for r in local["routes"]] == ["auth.example.com"]


def test_route_flags(client: TestClient, authed: dict[str, str]) -> None:
    state = _state(client)
    wildcard = _route(state, "*.apps.example.com")
    assert wildcard["wildcard"] and wildcard["can_block"]
    assert wildcard["block_disabled_reason"] is None
    foreign = _route(state, "other.elsewhere.org")
    assert foreign["block_disabled_reason"] == "no_zone_access"
    assert _route(state, "auth.example.com")["critical"]  # issuer host
    assert _route(state, "git.example.com")["critical"]  # CRITICAL_HOSTS
    assert _route(state, "vault.example.com")["origin_request"]["noTLSVerify"] is True


def test_block_and_allow_route(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    resp = client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    assert resp.status_code == 200, resp.text
    rule = fake_cf.rule()
    assert rule is not None
    assert rule["expression"] == '(lower(http.host) in {"vault.example.com"})'
    assert rule["action"] == "block" and rule["enabled"] is True
    assert _route(_state(client), "vault.example.com")["blocked"]

    client.post(
        "/api/routes/block",
        json={"hostname": "jellyfin.example.com", "blocked": True},
        headers=authed,
    )
    assert (
        fake_cf.rule()["expression"]
        == '(lower(http.host) in {"jellyfin.example.com" "vault.example.com"})'
    )

    client.post(
        "/api/routes/block",
        json={"hostname": "vault.example.com", "blocked": False},
        headers=authed,
    )
    client.post(
        "/api/routes/block",
        json={"hostname": "jellyfin.example.com", "blocked": False},
        headers=authed,
    )
    rule = fake_cf.rule()
    assert rule["enabled"] is False
    assert rule["expression"] == '(http.host eq "tunnelgate.invalid")'


def test_block_existing_ruleset_inserts_rule_first(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    fake_cf.rulesets[ZONE_ID] = {
        "id": "abcdef",
        "rules": [
            {"id": "aaa", "description": "skip bots", "action": "skip", "expression": "true"}
        ],
    }
    client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    rules = fake_cf.rulesets[ZONE_ID]["rules"]
    assert rules[0]["description"] == "tunnelgate-managed"
    assert rules[1]["description"] == "skip bots"


def test_critical_route_requires_confirmation(client: TestClient, authed: dict[str, str]) -> None:
    resp = client.post(
        "/api/routes/block", json={"hostname": "git.example.com", "blocked": True}, headers=authed
    )
    assert resp.status_code == 409 and resp.json()["confirm"] is True
    resp = client.post(
        "/api/routes/block",
        json={"hostname": "git.example.com", "blocked": True, "confirm_critical": True},
        headers=authed,
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        'vault.example.com" or true or "',
        "vault.example.com)",
        "unknown.example.com",
        "other.elsewhere.org",
        "a" * 300,
    ],
)
def test_block_rejects_invalid_or_unknown_hosts(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare, host: str
) -> None:
    resp = client.post(
        "/api/routes/block", json={"hostname": host, "blocked": True}, headers=authed
    )
    assert resp.status_code in (404, 422), resp.text
    assert fake_cf.rule() is None


def test_kill_all_and_block_tunnel(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    assert client.post("/api/kill-all", json={}, headers=authed).status_code == 409
    resp = client.post("/api/kill-all", json={"confirm": True}, headers=authed)
    assert resp.status_code == 200
    assert set(resp.json()["blocked"]) == {
        "git.example.com",
        "vault.example.com",
        "jellyfin.example.com",
        "auth.example.com",
        "*.apps.example.com",
    }
    assert resp.json()["skipped"] == ["other.elsewhere.org"]
    assert 'ends_with(lower(http.host), ".apps.example.com")' in fake_cf.rule()["expression"]
    resp = client.post(f"/api/tunnels/{T_MEDIA}/block-all", json={"confirm": True}, headers=authed)
    assert resp.status_code == 200
    assert "jellyfin.example.com" in resp.json()["blocked"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://evil.example.net"},
        {"Origin": APP},
        {"Origin": APP, "X-CSRF-Token": "wrong"},
    ],
)
def test_mutations_require_origin_and_csrf(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare, headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/routes/block",
        json={"hostname": "vault.example.com", "blocked": True},
        headers=headers,
    )
    assert resp.status_code == 403
    assert fake_cf.rule() is None


def test_referer_fallback_for_origin(client: TestClient, authed: dict[str, str]) -> None:
    headers = {"Referer": f"{APP}/settings", "X-CSRF-Token": authed["X-CSRF-Token"]}
    resp = client.post(
        "/api/routes/block",
        json={"hostname": "vault.example.com", "blocked": True},
        headers=headers,
    )
    assert resp.status_code == 200


def test_unknown_fields_are_rejected(client: TestClient, authed: dict[str, str]) -> None:
    resp = client.post(
        "/api/routes/block",
        json={"hostname": "vault.example.com", "blocked": True, "extra": 1},
        headers=authed,
    )
    assert resp.status_code == 422


def _clone_body(**overrides: object) -> dict:
    body = {
        "source_hostname": "vault.example.com",
        "subdomain": "vault-test",
        "zone_id": ZONE_ID,
        "service": "https://vaultwarden:443",
        "origin_request": {},
        "create_blocked": False,
    }
    body.update(overrides)
    return body


def test_clone_route_inserts_before_catch_all_and_creates_dns(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    resp = client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(), headers=authed)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "vault-test.example.com"
    ingress = fake_cf.configs[T_APPS]["config"]["ingress"]
    assert ingress[-2] == {
        "hostname": "vault-test.example.com",
        "service": "https://vaultwarden:443",
        "originRequest": {"noTLSVerify": True, "connectTimeout": 30},
    }
    assert ingress[-1] == {"service": "http_status:404"}
    assert fake_cf.configs[T_APPS]["config"]["warp-routing"] == {"enabled": False}
    rec = next(r for r in fake_cf.dns[ZONE_ID] if r["name"] == "vault-test.example.com")
    assert rec["content"] == f"{T_APPS}.cfargotunnel.com" and rec["proxied"] is True
    assert _state(client)["tunnels"][0]["can_undo"] is True


def test_clone_blocked_and_with_overrides(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    body = _clone_body(
        create_blocked=True,
        path="^/admin",
        origin_request={
            "noTLSVerify": None,
            "httpHostHeader": "Vault.Example.com",
            "connectTimeout": 10,
        },
    )
    resp = client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=body, headers=authed)
    assert resp.status_code == 200, resp.text
    new = fake_cf.configs[T_APPS]["config"]["ingress"][-2]
    assert new["path"] == "^/admin"
    assert new["originRequest"] == {"connectTimeout": 10, "httpHostHeader": "vault.example.com"}
    assert "vault-test.example.com" in fake_cf.rule()["expression"]
    # WAF block is applied before the route goes live.
    order = [c[0] + " " + c[1] for c in fake_cf.calls]
    waf_idx = max(i for i, c in enumerate(order) if "rulesets" in c and not c.startswith("GET"))
    put_idx = max(i for i, c in enumerate(order) if c.startswith("PUT") and "configurations" in c)
    assert waf_idx < put_idx


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"subdomain": "git"}, 409),
        ({"subdomain": "taken"}, 409),
        ({"subdomain": "bad_label"}, 422),
        ({"subdomain": "-x"}, 422),
        ({"zone_id": "c" * 32}, 422),
        ({"service": "http_status:404"}, 422),
        ({"service": "file:///etc/passwd"}, 422),
        ({"service": "http://user:pass@host"}, 422),
        ({"service": "http://host:99999"}, 422),
        ({"service": "ssh://host:22/path"}, 422),
        ({"origin_request": {"access": {"required": False}}}, 422),
        ({"origin_request": {"connectTimeout": 0}}, 422),
        ({"origin_request": {"noTLSVerify": "yes"}}, 422),
        ({"source_hostname": "missing.example.com"}, 404),
        ({"service": "http://127.0.0.1:8000"}, 422),
        ({"service": "http://localhost:8000"}, 422),
        ({"service": "https://169.254.169.254"}, 422),
        ({"service": "http://[::1]:80"}, 422),
        ({"service": "https://tunnelgate.int.example.com"}, 422),
        ({"service": "https://auth.example.com"}, 422),
        ({"origin_request": {"httpHostHeader": "tunnelgate.int.example.com"}}, 422),
        ({"origin_request": {"access": None}}, 422),
        ({"origin_request": {"ipRules": None}}, 422),
    ],
)
def test_clone_validation(
    client: TestClient,
    authed: dict[str, str],
    fake_cf: FakeCloudflare,
    overrides: dict,
    status: int,
) -> None:
    before = list(fake_cf.ingress_hosts(T_APPS))
    resp = client.post(
        f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(**overrides), headers=authed
    )
    assert resp.status_code == status, resp.text
    assert fake_cf.ingress_hosts(T_APPS) == before


def test_clone_into_local_tunnel_is_refused(client: TestClient, authed: dict[str, str]) -> None:
    body = _clone_body(source_hostname="auth.example.com", subdomain="auth2")
    resp = client.post(f"/api/tunnels/{T_LOCAL}/routes/clone", json=body, headers=authed)
    assert resp.status_code == 409


def test_clone_rolls_back_when_dns_fails(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    before = list(fake_cf.ingress_hosts(T_APPS))
    fake_cf.fail_next[("POST", rf"/zones/{ZONE_ID}/dns_records")] = fail(
        400, 81053, "record exists"
    )
    resp = client.post(
        f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(create_blocked=True), headers=authed
    )
    assert resp.status_code == 502
    assert fake_cf.ingress_hosts(T_APPS) == before
    rule = fake_cf.rule()
    assert rule is None or "vault-test" not in rule["expression"]
    assert not _state(client)["tunnels"][0]["can_undo"]


def test_invalid_tunnel_id_is_rejected(client: TestClient, authed: dict[str, str]) -> None:
    resp = client.post(
        "/api/tunnels/..%2F..%2Fzones/routes/clone", json=_clone_body(), headers=authed
    )
    assert resp.status_code in (404, 405, 422)


def test_remove_route_requires_typed_confirmation(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    body = {"hostname": "vault.example.com", "confirm": "vault"}
    resp = client.post(f"/api/tunnels/{T_APPS}/routes/remove", json=body, headers=authed)
    assert resp.status_code == 409
    assert "vault.example.com" in fake_cf.ingress_hosts(T_APPS)


def test_remove_route_deletes_rule_dns_and_block(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    body = {"hostname": "vault.example.com", "confirm": "vault.example.com"}
    resp = client.post(f"/api/tunnels/{T_APPS}/routes/remove", json=body, headers=authed)
    assert resp.status_code == 200, resp.text
    assert "vault.example.com" not in fake_cf.ingress_hosts(T_APPS)
    assert not any(r["name"] == "vault.example.com" for r in fake_cf.dns[ZONE_ID])
    assert fake_cf.rule()["enabled"] is False
    assert fake_cf.ingress_hosts(T_APPS)[-1] is None


def test_undo_restores_previous_config(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    before = list(fake_cf.ingress_hosts(T_APPS))
    client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(), headers=authed)
    assert fake_cf.ingress_hosts(T_APPS) != before
    assert (
        client.post(
            f"/api/tunnels/{T_APPS}/undo", json={"confirm": True}, headers=authed
        ).status_code
        == 200
    )
    assert fake_cf.ingress_hosts(T_APPS) == before
    assert (
        client.post(
            f"/api/tunnels/{T_APPS}/undo", json={"confirm": True}, headers=authed
        ).status_code
        == 404
    )


def test_cloudflare_errors_are_reported_as_502(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    fake_cf.fail_next[("GET", "/zones")] = fail(403, 10000, "Authentication error")
    resp = client.get("/api/state", params={"refresh": "true"})
    assert resp.status_code == 502
    assert "cf-test-token" not in resp.text


def test_about(client: TestClient, authed: dict[str, str]) -> None:
    body = client.get("/api/about").json()
    assert body["cloudflare_ok"] is True and body["zones"] == ["example.com"]


def test_security_headers_and_csp_hash(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    csp = resp.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "'sha256-" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert INLINE_SCRIPT in resp.text
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["strict-transport-security"].startswith("max-age=")
    assert client.get("/api/me").headers["cache-control"] == "no-store"
    assert client.get("/_app/immutable/app.js").headers["cache-control"].endswith("immutable")


def test_spa_fallback_and_api_404(client: TestClient) -> None:
    assert client.get("/settings").status_code == 200
    assert client.get("/api/nope").status_code == 404
    assert client.get("/../../etc/passwd").status_code in (200, 404)
    assert "root:" not in client.get("/..%2F..%2Fetc%2Fpasswd").text


def test_untrusted_host_header_is_rejected(client: TestClient) -> None:
    assert client.get("/healthz", headers={"Host": "evil.example.net"}).status_code == 400
    assert client.get("/healthz", headers={"Host": "127.0.0.1:8000"}).status_code == 200


def test_large_body_is_rejected(client: TestClient, authed: dict[str, str]) -> None:
    payload = "x" * (70 * 1024)
    resp = client.post(
        "/api/routes/block", content=payload, headers={**authed, "content-type": "application/json"}
    )
    assert resp.status_code == 413


def test_audit_log_records_actions(client: TestClient, authed: dict[str, str]) -> None:
    client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    store = client.app.state.store  # type: ignore[attr-defined]
    rows = store._conn.execute("SELECT actor, action, target, outcome FROM audit_log").fetchall()
    assert ("gabriel", "login", "tunnelgate", "ok") in rows
    assert ("gabriel", "block", "vault.example.com", "ok") in rows


def test_clone_defaults_to_blocked(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    body = _clone_body()
    del body["create_blocked"]
    assert (
        client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=body, headers=authed).status_code
        == 200
    )
    assert "vault-test.example.com" in fake_cf.rule()["expression"]


def test_clone_keeps_inherited_access_settings(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    rule = fake_cf.configs[T_APPS]["config"]["ingress"][1]
    rule["originRequest"]["access"] = {"required": True, "teamName": "home"}
    body = _clone_body(origin_request={"noTLSVerify": None})
    assert (
        client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=body, headers=authed).status_code
        == 200
    )
    new = next(
        r
        for r in fake_cf.configs[T_APPS]["config"]["ingress"]
        if r.get("hostname") == "vault-test.example.com"
    )
    assert new["originRequest"] == {
        "connectTimeout": 30,
        "access": {"required": True, "teamName": "home"},
    }


def test_clone_is_inserted_before_covering_wildcard(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    body = _clone_body(subdomain="new.apps")
    assert (
        client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=body, headers=authed).status_code
        == 200
    )
    hosts = fake_cf.ingress_hosts(T_APPS)
    assert hosts.index("new.apps.example.com") < hosts.index("*.apps.example.com")


def test_wildcard_route_can_be_blocked(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    resp = client.post(
        "/api/routes/block",
        json={"hostname": "*.apps.example.com", "blocked": True},
        headers=authed,
    )
    assert resp.status_code == 200, resp.text
    assert fake_cf.rule()["expression"] == 'ends_with(lower(http.host), ".apps.example.com")'
    assert _route(_state(client), "*.apps.example.com")["blocked"]


def test_service_allowlist(settings, fake_cf: FakeCloudflare, oidc, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    from tests.conftest import csrf_headers, login
    from tunnelgate.app import create_app
    from tunnelgate.config import Settings

    monkeypatch.setenv("SERVICE_ALLOWLIST", "*.lan:*,vaultwarden:443")
    app = create_app(Settings(), cf_transport=httpx.MockTransport(fake_cf.handler))
    with TestClient(app, base_url=APP, follow_redirects=False) as c:
        login(c, oidc)
        h = csrf_headers(c)
        ok = c.post(f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(), headers=h)
        assert ok.status_code == 200, ok.text
        bad = c.post(
            f"/api/tunnels/{T_APPS}/routes/clone",
            json=_clone_body(subdomain="other", service="http://proxmox:8006"),
            headers=h,
        )
        assert bad.status_code == 422 and "SERVICE_ALLOWLIST" in bad.text


def test_remove_stale_rule_keeps_block_for_host_served_elsewhere(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    ingress = fake_cf.configs[T_APPS]["config"]["ingress"]
    ingress.insert(0, {"hostname": "jellyfin.example.com", "service": "http://old:1"})
    client.post(
        "/api/routes/block",
        json={"hostname": "jellyfin.example.com", "blocked": True},
        headers=authed,
    )
    body = {"hostname": "jellyfin.example.com", "confirm": "jellyfin.example.com"}
    assert (
        client.post(f"/api/tunnels/{T_APPS}/routes/remove", json=body, headers=authed).status_code
        == 200
    )
    assert "jellyfin.example.com" in fake_cf.rule()["expression"]
    assert any(r["name"] == "jellyfin.example.com" for r in fake_cf.dns[ZONE_ID])


def test_undo_after_clone_removes_dns(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(), headers=authed)
    assert any(r["name"] == "vault-test.example.com" for r in fake_cf.dns[ZONE_ID])
    assert (
        client.post(
            f"/api/tunnels/{T_APPS}/undo", json={"confirm": True}, headers=authed
        ).status_code
        == 200
    )
    assert not any(r["name"] == "vault-test.example.com" for r in fake_cf.dns[ZONE_ID])
    assert (
        client.post(
            f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(), headers=authed
        ).status_code
        == 200
    )


def test_undo_after_remove_restores_route_still_blocked(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    body = {"hostname": "vault.example.com", "confirm": "vault.example.com"}
    client.post(f"/api/tunnels/{T_APPS}/routes/remove", json=body, headers=authed)
    assert fake_cf.rule()["enabled"] is False
    assert (
        client.post(
            f"/api/tunnels/{T_APPS}/undo", json={"confirm": True}, headers=authed
        ).status_code
        == 200
    )
    assert "vault.example.com" in fake_cf.ingress_hosts(T_APPS)
    assert "vault.example.com" in fake_cf.rule()["expression"] and fake_cf.rule()["enabled"]
    assert any(r["name"] == "vault.example.com" for r in fake_cf.dns[ZONE_ID])


def test_undo_refuses_when_config_changed_afterwards(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    client.post(f"/api/tunnels/{T_APPS}/routes/clone", json=_clone_body(), headers=authed)
    fake_cf.configs[T_APPS]["config"]["ingress"].insert(
        0, {"hostname": "manual.example.com", "service": "http://m"}
    )
    resp = client.post(f"/api/tunnels/{T_APPS}/undo", json={"confirm": True}, headers=authed)
    assert resp.status_code == 409
    assert "manual.example.com" in fake_cf.ingress_hosts(T_APPS)


def test_kill_all_continues_past_failing_zone(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    from tests.conftest import OTHER_ZONE_ID

    fake_cf.zones.append({"id": OTHER_ZONE_ID, "name": "elsewhere.org"})
    fake_cf.dns[OTHER_ZONE_ID] = []
    entry = r"/zones/{}/rulesets/phases/http_request_firewall_custom/entrypoint"
    fake_cf.fail_next[("PUT", entry.format(ZONE_ID))] = fail(403, 10000, "denied")
    resp = client.post("/api/kill-all", json={"confirm": True}, headers=authed)
    assert resp.status_code == 502
    body = resp.json()
    assert body["blocked"] == ["other.elsewhere.org"]
    assert "vault.example.com" in body["failed"]
    assert "other.elsewhere.org" in fake_cf.rule(OTHER_ZONE_ID)["expression"]


def test_forced_refresh_is_throttled(
    client: TestClient,
    authed: dict[str, str],
    fake_cf: FakeCloudflare,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setattr("tunnelgate.service.MIN_REFRESH_INTERVAL", 60.0)
    client.get("/api/state", params={"refresh": "true"})
    before = len(fake_cf.calls)
    for _ in range(5):
        client.get("/api/state", params={"refresh": "true"})
    assert len(fake_cf.calls) == before


def test_waf_write_is_retried_when_response_does_not_match(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    import httpx

    from tests.conftest import ok

    client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    state = {"n": 0}

    def racing(request: httpx.Request) -> httpx.Response:
        resp = fake_cf.handler(request)
        if request.method == "PATCH" and state["n"] == 0:
            state["n"] = 1
            fake_cf.rule()["expression"] = '(lower(http.host) in {"git.example.com"})'  # type: ignore[index]
            return ok(fake_cf.rulesets[ZONE_ID])
        return resp

    client.app.state.service.cf._http._transport = httpx.MockTransport(racing)  # type: ignore[attr-defined]
    client.post(
        "/api/routes/block",
        json={"hostname": "jellyfin.example.com", "blocked": True},
        headers=authed,
    )
    assert "jellyfin.example.com" in fake_cf.rule()["expression"]
    assert state["n"] == 1


def test_toggle_reuses_cached_routes_and_returns_state(
    client: TestClient,
    authed: dict[str, str],
    fake_cf: FakeCloudflare,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setattr("tunnelgate.service.CACHE_TTL", 0.0)
    _state(client)
    before = len(fake_cf.calls)
    resp = client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    assert resp.status_code == 200, resp.text
    calls = fake_cf.calls[before:]
    # One read and one write of the WAF rule: no discovery, no read-back.
    assert [m for m, _, _ in calls] == ["GET", "PUT"]
    assert all("/rulesets/" in p for _, p, _ in calls)
    state = resp.json()["state"]
    assert _route(state, "vault.example.com")["blocked"]
    assert not _route(state, "git.example.com")["blocked"]


def test_toggle_discovers_when_route_is_not_cached(
    client: TestClient, authed: dict[str, str], fake_cf: FakeCloudflare
) -> None:
    resp = client.post(
        "/api/routes/block", json={"hostname": "vault.example.com", "blocked": True}, headers=authed
    )
    assert resp.status_code == 200, resp.text
    assert any(p.endswith("/cfd_tunnel") for _, p, _ in fake_cf.calls)
    assert _route(resp.json()["state"], "vault.example.com")["blocked"]


def test_bulk_block_returns_state(client: TestClient, authed: dict[str, str]) -> None:
    resp = client.post("/api/kill-all", json={"confirm": True}, headers=authed)
    assert resp.status_code == 200
    routes = [r for t in resp.json()["state"]["tunnels"] for r in t["routes"]]
    assert all(r["blocked"] for r in routes if r["can_block"])
    assert not any(r["blocked"] for r in routes if not r["can_block"])
