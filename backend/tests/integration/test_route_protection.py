"""Every route outside an explicit public list must require a session (and CSRF for writes)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.conftest import APP, T_APPS
from tunnelgate.auth import require_csrf, require_user

PUBLIC = {
    ("GET", "/healthz"),
    ("GET", "/api/me"),
    ("GET", "/auth/login"),
    ("POST", "/auth/login"),
    ("GET", "/auth/callback"),
    ("POST", "/auth/logout"),
}


def all_routes(app: FastAPI) -> list[tuple[str, str, APIRoute]]:
    """Flatten app routes; included routers are wrapped in newer FastAPI versions."""
    found: list[tuple[str, str, APIRoute]] = []
    for route in app.routes:
        router: Any = getattr(route, "original_router", None)
        candidates = router.routes if router is not None else [route]
        for r in candidates:
            if isinstance(r, APIRoute):
                found += [(m, r.path, r) for m in sorted(r.methods)]
    return found


@pytest.fixture(params=["oidc", "password"])
def any_client(request: pytest.FixtureRequest) -> TestClient:
    return request.getfixturevalue("client" if request.param == "oidc" else "password_client")  # type: ignore[no-any-return]


def test_inventory_is_complete(any_client: TestClient) -> None:
    routes = all_routes(any_client.app)  # type: ignore[arg-type]
    assert len([r for r in routes if r[1].startswith("/api/")]) >= 9


def test_private_routes_depend_on_auth(any_client: TestClient) -> None:
    for method, path, route in all_routes(any_client.app):  # type: ignore[arg-type]
        if (method, path) in PUBLIC:
            continue
        deps = {d.call for d in route.dependant.dependencies}
        needed = require_user if method == "GET" else require_csrf
        assert needed in deps, f"{method} {path} is not protected"


def test_private_routes_reject_anonymous(any_client: TestClient) -> None:
    for method, path, _ in all_routes(any_client.app):  # type: ignore[arg-type]
        if (method, path) in PUBLIC:
            continue
        resp = any_client.request(
            method, path.replace("{tunnel_id}", T_APPS), json={}, headers={"Origin": APP}
        )
        assert resp.status_code == 401, (method, path, resp.status_code)
