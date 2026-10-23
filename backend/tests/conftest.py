from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from tunnelgate.app import create_app
from tunnelgate.config import Settings

ACCOUNT = "0123456789abcdef0123456789abcdef"
ZONE_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER_ZONE_ID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
T_APPS = "11111111-1111-4111-8111-111111111111"
T_MEDIA = "22222222-2222-4222-8222-222222222222"
T_LOCAL = "33333333-3333-4333-8333-333333333333"
APP = "https://tunnelgate.int.example.com"
ISSUER = "https://auth.example.com"
INLINE_SCRIPT = "console.log('boot')"


def ok(result: Any, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "errors": [], "result": result, **extra})


def fail(status: int, code: int = 1000, message: str = "error") -> httpx.Response:
    return httpx.Response(
        status, json={"success": False, "errors": [{"code": code, "message": message}]}
    )


@dataclass
class FakeCloudflare:
    """Stateful in-memory stand-in for the Cloudflare endpoints Tunnelgate calls."""

    zones: list[dict[str, Any]] = field(default_factory=list)
    tunnels: list[dict[str, Any]] = field(default_factory=list)
    configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    dns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    rulesets: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    fail_next: dict[tuple[str, str], httpx.Response] = field(default_factory=dict)

    def handler(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path.removeprefix("/client/v4")
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))
        for (m, pattern), response in list(self.fail_next.items()):
            if m == method and re.fullmatch(pattern, path):
                del self.fail_next[(m, pattern)]
                return response
        q = parse_qs(request.url.query.decode())
        acct = f"/accounts/{ACCOUNT}"

        if method == "GET" and path == "/zones":
            return ok(self.zones, result_info={"total_pages": 1})
        if method == "GET" and path == f"{acct}/cfd_tunnel":
            return ok(self.tunnels, result_info={"total_pages": 1})
        if method == "GET" and path in (f"{acct}/tokens/verify", "/user/tokens/verify"):
            return ok({"status": "active", "expires_on": None})
        if m := re.fullmatch(rf"{acct}/cfd_tunnel/([0-9a-f-]+)/configurations", path):
            tid = m.group(1)
            if method == "GET":
                if tid not in self.configs:
                    return fail(404, 1003, "not found")
                return ok(self.configs[tid])
            if method == "PUT":
                assert body is not None
                self.configs[tid] = {"tunnel_id": tid, "source": "cloudflare", **body}
                return ok(self.configs[tid])
        if m := re.fullmatch(r"/zones/([0-9a-f]{32})/dns_records", path):
            records = self.dns.setdefault(m.group(1), [])
            if method == "GET":
                items = records
                if "type" in q:
                    items = [r for r in items if r["type"] == q["type"][0]]
                if "name" in q:
                    items = [r for r in items if r["name"] == q["name"][0]]
                return ok(items, result_info={"total_pages": 1})
            if method == "POST":
                assert body is not None
                rec = {"id": uuid.uuid4().hex, **body}
                records.append(rec)
                return ok(rec)
        if m := re.fullmatch(r"/zones/([0-9a-f]{32})/dns_records/([0-9a-f]+)", path):
            if method == "DELETE":
                self.dns[m.group(1)] = [r for r in self.dns[m.group(1)] if r["id"] != m.group(2)]
                return ok({"id": m.group(2)})
        if m := re.fullmatch(
            r"/zones/([0-9a-f]{32})/rulesets/phases/http_request_firewall_custom/entrypoint", path
        ):
            zid = m.group(1)
            if method == "GET":
                return ok(self.rulesets[zid]) if zid in self.rulesets else fail(404, 10003)
            if method == "PUT":
                assert body is not None
                rules = [{"id": uuid.uuid4().hex, **r} for r in body["rules"]]
                self.rulesets[zid] = {"id": uuid.uuid4().hex, "rules": rules}
                return ok(self.rulesets[zid])
        if m := re.fullmatch(r"/zones/([0-9a-f]{32})/rulesets/([0-9a-f]+)/rules", path):
            assert method == "POST" and body is not None
            rs = self.rulesets[m.group(1)]
            rule = {"id": uuid.uuid4().hex, **{k: v for k, v in body.items() if k != "position"}}
            idx = (body.get("position") or {}).get("index")
            rs["rules"].insert(idx - 1 if idx else len(rs["rules"]), rule)
            return ok(rs)
        if m := re.fullmatch(r"/zones/([0-9a-f]{32})/rulesets/([0-9a-f]+)/rules/([0-9a-f]+)", path):
            assert method == "PATCH" and body is not None
            rs = self.rulesets[m.group(1)]
            for rule in rs["rules"]:
                if rule["id"] == m.group(3):
                    rule.update(body)
            return ok(rs)
        return fail(404, 7003, f"no route for {method} {path}")

    def rule(self, zone_id: str = ZONE_ID) -> dict[str, Any] | None:
        for r in self.rulesets.get(zone_id, {}).get("rules", []):
            if r.get("description") == "tunnelgate-managed":
                return r  # type: ignore[no-any-return]
        return None

    def ingress_hosts(self, tunnel_id: str) -> list[str | None]:
        return [r.get("hostname") for r in self.configs[tunnel_id]["config"]["ingress"]]


def make_fake() -> FakeCloudflare:
    fake = FakeCloudflare()
    fake.zones = [{"id": ZONE_ID, "name": "example.com"}]
    fake.tunnels = [
        {"id": T_APPS, "name": "apps", "status": "healthy", "connections": [{}, {}, {}, {}]},
        {"id": T_MEDIA, "name": "media", "status": "down", "connections": []},
        {"id": T_LOCAL, "name": "auth", "status": "healthy", "connections": [{}, {}]},
    ]
    fake.configs = {
        T_APPS: {
            "source": "cloudflare",
            "config": {
                "ingress": [
                    {"hostname": "git.example.com", "service": "http://gitea:3000"},
                    {
                        "hostname": "vault.example.com",
                        "service": "https://vaultwarden:443",
                        "originRequest": {"noTLSVerify": True, "connectTimeout": 30},
                    },
                    {"hostname": "*.apps.example.com", "service": "https://swag:443"},
                    {"hostname": "other.elsewhere.org", "service": "http://x:1"},
                    {"service": "http_status:404"},
                ],
                "warp-routing": {"enabled": False},
            },
        },
        T_MEDIA: {
            "source": "cloudflare",
            "config": {
                "ingress": [
                    {"hostname": "jellyfin.example.com", "service": "http://jellyfin:8096"},
                    {"service": "http_status:404"},
                ]
            },
        },
        T_LOCAL: {"source": "local", "config": None},
    }

    def cname(host: str, tid: str) -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "type": "CNAME",
            "name": host,
            "content": f"{tid}.cfargotunnel.com",
            "proxied": True,
        }

    fake.dns = {
        ZONE_ID: [
            cname("git.example.com", T_APPS),
            cname("vault.example.com", T_APPS),
            cname("*.apps.example.com", T_APPS),
            cname("jellyfin.example.com", T_MEDIA),
            cname("auth.example.com", T_LOCAL),
            {
                "id": uuid.uuid4().hex,
                "type": "A",
                "name": "taken.example.com",
                "content": "1.2.3.4",
            },
        ]
    }
    return fake


@dataclass
class FakeOidc:
    key: RSAKey
    claims: dict[str, Any] = field(default_factory=dict)
    userinfo: dict[str, Any] = field(default_factory=dict)
    nonce: str | None = None
    end_session: bool = False
    discovery_down: bool = False

    def id_token(self) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "tunnelgate",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            **self.claims,
        }
        return jwt.encode({"alg": "RS256", "kid": "test"}, claims, self.key)


def default_claims() -> dict[str, Any]:
    return {"sub": "user-1", "preferred_username": "gabriel", "amr": ["pwd", "otp", "mfa"]}


def default_userinfo() -> dict[str, Any]:
    return {"sub": "user-1", "name": "Gabriel", "groups": ["Users", "HomeAdmins"]}


@pytest.fixture
def fake_cf() -> FakeCloudflare:
    return make_fake()


@pytest.fixture
def oidc() -> Iterator[FakeOidc]:
    provider = FakeOidc(
        key=RSAKey.generate_key(2048, parameters={"kid": "test"}),
        claims=default_claims(),
        userinfo=default_userinfo(),
    )
    with respx.mock(assert_all_called=False) as mock:

        def discovery(_: httpx.Request) -> httpx.Response:
            if provider.discovery_down:
                raise httpx.ConnectError("down")
            doc = {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/api/oidc/authorization",
                "token_endpoint": f"{ISSUER}/api/oidc/token",
                "userinfo_endpoint": f"{ISSUER}/api/oidc/userinfo",
                "jwks_uri": f"{ISSUER}/jwks.json",
                "id_token_signing_alg_values_supported": ["RS256"],
            }
            if provider.end_session:
                doc["end_session_endpoint"] = f"{ISSUER}/api/oidc/end-session"
            return httpx.Response(200, json=doc)

        mock.get(f"{ISSUER}/.well-known/openid-configuration").mock(side_effect=discovery)
        mock.get(f"{ISSUER}/jwks.json").mock(
            side_effect=lambda _: httpx.Response(
                200, json={"keys": [provider.key.as_dict(private=False)]}
            )
        )
        mock.post(f"{ISSUER}/api/oidc/token").mock(
            side_effect=lambda _: httpx.Response(
                200,
                json={
                    "access_token": "at",
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "id_token": provider.id_token(),
                },
            )
        )
        mock.get(f"{ISSUER}/api/oidc/userinfo").mock(
            side_effect=lambda _: httpx.Response(200, json=provider.userinfo)
        )
        yield provider


def write_static(root: Path) -> Path:
    static = root / "static"
    (static / "_app" / "immutable").mkdir(parents=True)
    page = (
        f"<!doctype html><html><head><script>{INLINE_SCRIPT}</script></head><body>spa</body></html>"
    )
    (static / "200.html").write_text(page)
    (static / "index.html").write_text(page)
    (static / "_app" / "immutable" / "app.js").write_text("export {}")
    return static


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    env = {
        "CF_API_TOKEN": "cf-test-token",
        "CF_ACCOUNT_ID": ACCOUNT,
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": "tunnelgate",
        "OIDC_CLIENT_SECRET": "oidc-secret",
        "APP_URL": APP,
        "ALLOWED_GROUPS": "HomeAdmins",
        "CRITICAL_HOSTS": "git.example.com",
        "TUNNELGATE_DATA_DIR": str(tmp_path / "data"),
        "TUNNELGATE_STATIC_DIR": str(write_static(tmp_path)),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


@pytest.fixture
def client(settings: Settings, fake_cf: FakeCloudflare, oidc: FakeOidc) -> Iterator[TestClient]:
    app = create_app(settings, cf_transport=httpx.MockTransport(fake_cf.handler))
    with TestClient(app, base_url=APP, follow_redirects=False) as c:
        yield c


def login(client: TestClient, oidc: FakeOidc) -> httpx.Response:
    start = client.get("/auth/login")
    assert start.status_code in (302, 303, 307), start.text
    query = parse_qs(urlsplit(start.headers["location"]).query)
    oidc.nonce = query["nonce"][0]
    return client.get("/auth/callback", params={"code": "abc", "state": query["state"][0]})


def csrf_headers(client: TestClient) -> dict[str, str]:
    me = client.get("/api/me")
    assert me.status_code == 200, me.text
    return {"Origin": APP, "X-CSRF-Token": me.json()["csrf_token"]}


@pytest.fixture
def authed(client: TestClient, oidc: FakeOidc) -> dict[str, str]:
    resp = login(client, oidc)
    assert resp.headers["location"] == "/", resp.text
    return csrf_headers(client)
