"""Thin async client for the Cloudflare v4 API endpoints Tunnelgate uses."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

JSON = dict[str, Any]
WAF_PHASE = "http_request_firewall_custom"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_PAGES = 100


class CloudflareError(Exception):
    """A Cloudflare API call failed."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _error_message(data: Any) -> str:
    if isinstance(data, dict):
        errors = data.get("errors") or []
        parts = [f"{e.get('code')}: {e.get('message')}" for e in errors if isinstance(e, dict)]
        if parts:
            return "; ".join(parts)[:500]
    return "unexpected response from Cloudflare"


class CloudflareClient:
    def __init__(
        self,
        token: str,
        account_id: str,
        base_url: str = "https://api.cloudflare.com/client/v4",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.account_id = account_id
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "tunnelgate"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,
            follow_redirects=False,
        )
        self._sem = asyncio.Semaphore(6)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self, method: str, path: str, expected: frozenset[int] = frozenset(), **kwargs: Any
    ) -> JSON:
        async with self._sem:
            for attempt in range(3):
                try:
                    resp = await self._http.request(method, path, **kwargs)
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        raise CloudflareError(502, f"network error: {type(exc).__name__}") from exc
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                if resp.status_code in _RETRY_STATUS and attempt < 2:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                break
        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.status_code >= 400 or not isinstance(data, dict) or not data.get("success"):
            msg = _error_message(data)
            level = logging.DEBUG if resp.status_code in expected else logging.WARNING
            log.log(level, "cloudflare %s %s -> %s: %s", method, path, resp.status_code, msg)
            raise CloudflareError(resp.status_code, msg)
        return data

    async def _paged(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = 100
    ) -> list[JSON]:
        items: list[JSON] = []
        for page in range(1, _MAX_PAGES + 1):
            q = {**(params or {}), "page": page, "per_page": per_page}
            data = await self._request("GET", path, params=q)
            batch = data.get("result") or []
            items.extend(batch)
            info = data.get("result_info") or {}
            total_pages = info.get("total_pages")
            if total_pages is not None and page >= int(total_pages):
                break
            if total_pages is None and len(batch) < per_page:
                break
        return items

    async def verify_token(self) -> JSON:
        try:
            data = await self._request("GET", f"/accounts/{self.account_id}/tokens/verify")
        except CloudflareError:
            data = await self._request("GET", "/user/tokens/verify")
        result: JSON = data["result"]
        return result

    async def list_zones(self) -> list[JSON]:
        return await self._paged("/zones", per_page=50)

    async def list_tunnels(self) -> list[JSON]:
        return await self._paged(f"/accounts/{self.account_id}/cfd_tunnel", {"is_deleted": "false"})

    async def get_tunnel_config(self, tunnel_id: str) -> JSON:
        data = await self._request(
            "GET", f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations"
        )
        result: JSON = data.get("result") or {}
        return result

    async def put_tunnel_config(self, tunnel_id: str, config: JSON) -> JSON:
        data = await self._request(
            "PUT",
            f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations",
            json={"config": config},
        )
        result: JSON = data.get("result") or {}
        return result

    async def list_cname_records(self, zone_id: str) -> list[JSON]:
        return await self._paged(f"/zones/{zone_id}/dns_records", {"type": "CNAME"}, per_page=500)

    async def list_records_by_name(self, zone_id: str, name: str) -> list[JSON]:
        return await self._paged(f"/zones/{zone_id}/dns_records", {"name": name}, per_page=100)

    async def create_cname(self, zone_id: str, name: str, target: str) -> JSON:
        data = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json={
                "type": "CNAME",
                "name": name,
                "content": target,
                "proxied": True,
                "ttl": 1,
                "comment": "Managed by Tunnelgate",
            },
        )
        result: JSON = data["result"]
        return result

    async def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        await self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")

    async def get_waf_entrypoint(self, zone_id: str) -> JSON | None:
        try:
            # No custom rules in the zone yet.
            data = await self._request(
                "GET",
                f"/zones/{zone_id}/rulesets/phases/{WAF_PHASE}/entrypoint",
                expected=frozenset({404}),
            )
        except CloudflareError as exc:
            if exc.status == 404:
                return None
            raise
        result: JSON = data["result"]
        return result

    async def create_waf_entrypoint(self, zone_id: str, rule: JSON) -> JSON:
        data = await self._request(
            "PUT",
            f"/zones/{zone_id}/rulesets/phases/{WAF_PHASE}/entrypoint",
            json={"rules": [rule]},
        )
        result: JSON = data["result"]
        return result

    async def add_waf_rule(self, zone_id: str, ruleset_id: str, rule: JSON) -> JSON:
        path = f"/zones/{zone_id}/rulesets/{ruleset_id}/rules"
        try:
            data = await self._request("POST", path, json={**rule, "position": {"index": 1}})
        except CloudflareError as exc:
            if exc.status != 400:
                raise
            log.info("rule position not accepted, appending instead")
            data = await self._request("POST", path, json=rule)
        result: JSON = data["result"]
        return result

    async def update_waf_rule(
        self, zone_id: str, ruleset_id: str, rule_id: str, rule: JSON
    ) -> JSON:
        data = await self._request(
            "PATCH", f"/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}", json=rule
        )
        result: JSON = data["result"]
        return result
