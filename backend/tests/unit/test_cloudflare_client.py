from __future__ import annotations

import httpx2
import pytest

from tests.conftest import ACCOUNT
from tunnelgate import cloudflare as cfmod
from tunnelgate.cloudflare import CloudflareClient, CloudflareError


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(cfmod.asyncio, "sleep", instant)


def client(handler: object) -> CloudflareClient:
    return CloudflareClient("secret-token", ACCOUNT, transport=httpx2.MockTransport(handler))  # type: ignore[arg-type]


async def test_retries_on_429_then_succeeds() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.headers["authorization"])
        if len(calls) < 3:
            return httpx2.Response(429, json={"success": False, "errors": []})
        return httpx2.Response(
            200, json={"success": True, "result": [{"id": "z", "name": "a.com"}]}
        )

    cf = client(handler)
    assert await cf.list_zones() == [{"id": "z", "name": "a.com"}]
    assert calls == ["Bearer secret-token"] * 3
    await cf.aclose()


async def test_pagination_follows_total_pages() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        page = int(request.url.params["page"])
        return httpx2.Response(
            200,
            json={
                "success": True,
                "result": [{"id": str(page)}],
                "result_info": {"total_pages": 3},
            },
        )

    cf = client(handler)
    assert [z["id"] for z in await cf.list_zones()] == ["1", "2", "3"]
    await cf.aclose()


async def test_pagination_without_total_pages_stops_on_short_page() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        page = int(request.url.params["page"])
        per = int(request.url.params["per_page"])
        size = per if page == 1 else 1
        return httpx2.Response(200, json={"success": True, "result": [{"id": "x"}] * size})

    cf = client(handler)
    assert len(await cf.list_tunnels()) == 101
    await cf.aclose()


async def test_errors_are_sanitized_and_never_include_the_token() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            403,
            json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]},
        )

    cf = client(handler)
    with pytest.raises(CloudflareError) as info:
        await cf.list_zones()
    assert info.value.status == 403
    assert "10000: Authentication error" in info.value.message
    assert "secret-token" not in info.value.message
    await cf.aclose()


async def test_non_json_and_network_errors() -> None:
    def bad(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>")

    cf = client(bad)
    with pytest.raises(CloudflareError, match="unexpected response"):
        await cf.list_zones()
    await cf.aclose()

    def boom(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    cf = client(boom)
    with pytest.raises(CloudflareError, match="network error") as info:
        await cf.list_zones()
    assert info.value.status == 502
    await cf.aclose()


async def test_verify_token_falls_back_to_user_endpoint() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith(f"/accounts/{ACCOUNT}/tokens/verify"):
            return httpx2.Response(404, json={"success": False, "errors": []})
        return httpx2.Response(200, json={"success": True, "result": {"status": "active"}})

    cf = client(handler)
    assert (await cf.verify_token())["status"] == "active"
    await cf.aclose()


async def test_add_rule_falls_back_when_position_rejected() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        import json

        body = json.loads(request.content)
        bodies.append(body)
        if "position" in body:
            return httpx2.Response(
                400, json={"success": False, "errors": [{"code": 1, "message": "bad"}]}
            )
        return httpx2.Response(200, json={"success": True, "result": {"id": "rs"}})

    cf = client(handler)
    await cf.add_waf_rule("z" * 32, "rs", {"action": "block"})
    assert "position" in bodies[0] and "position" not in bodies[1]
    await cf.aclose()


async def test_missing_waf_entrypoint_is_not_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            404, json={"success": False, "errors": [{"code": 10003, "message": "not found"}]}
        )

    cf = client(handler)
    with caplog.at_level("DEBUG", logger="tunnelgate.cloudflare"):
        assert await cf.get_waf_entrypoint("z") is None
    assert [r.levelname for r in caplog.records] == ["DEBUG"]
    await cf.aclose()
