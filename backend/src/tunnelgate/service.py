"""Tunnel discovery, blocking and route lifecycle."""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any

from tunnelgate.cloudflare import JSON, CloudflareClient, CloudflareError
from tunnelgate.locks import LockManager
from tunnelgate.schemas import CloneRequest, Route, State, Tunnel, TunnelStatus, Zone
from tunnelgate.store import Store
from tunnelgate.validation import (
    ServicePolicy,
    ValidationError,
    build_hostname,
    hostname_in_zone,
    is_hostname,
    is_wildcard,
    normalize_route_hostname,
    validate_optional_hostname,
    validate_path,
    validate_service,
    zone_for,
)
from tunnelgate.waf import WafError, WafManager

log = logging.getLogger(__name__)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_TUNNEL_TARGET_RE = re.compile(r"^([0-9a-f-]{36})\.cfargotunnel\.com$")
_STATUSES: frozenset[str] = frozenset({"healthy", "degraded", "down", "inactive"})
CACHE_TTL = 10.0
MIN_REFRESH_INTERVAL = 3.0

_BOOL_KEYS = frozenset({"noTLSVerify", "noHappyEyeballs", "disableChunkedEncoding", "http2Origin"})
_HOST_KEYS = frozenset({"httpHostHeader", "originServerName"})
_INT_KEYS = {"connectTimeout": 600, "tlsTimeout": 600, "keepAliveTimeout": 3600}
_EDITABLE_KEYS = _BOOL_KEYS | _HOST_KEYS | frozenset(_INT_KEYS)


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class ConfirmationRequiredError(Exception):
    pass


class PartialBlockError(Exception):
    """Some zones could not be updated; part of the requested block did not happen."""

    def __init__(self, blocked: list[str], failed: list[str], skipped: list[str]) -> None:
        super().__init__("some routes could not be blocked")
        self.blocked = blocked
        self.failed = failed
        self.skipped = skipped


@dataclass
class BlockResult:
    blocked: list[str]
    skipped: list[str] = field(default_factory=list)


@dataclass
class _Snapshot:
    state: State
    zones: dict[str, str]
    routes: dict[str, set[str]] = field(default_factory=dict)  # hostname -> tunnel ids
    at: float = 0.0


def validate_tunnel_id(tunnel_id: str) -> str:
    if not UUID_RE.fullmatch(tunnel_id):
        raise ValidationError("invalid tunnel id")
    return tunnel_id


def apply_origin_overrides(
    base: dict[str, Any], overrides: dict[str, Any], forbidden_hosts: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Merge user edits into a copied originRequest.

    Only known, typed keys can be set or cleared; anything else inherited from the source
    rule (Access enforcement, IP rules, proxy settings) is kept untouched.
    """
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key not in _EDITABLE_KEYS:
            raise ValidationError(f"unsupported originRequest option: {key}")
        if value is None:
            result.pop(key, None)
        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise ValidationError(f"{key} must be a boolean")
            result[key] = value
        elif key in _HOST_KEYS:
            if not isinstance(value, str):
                raise ValidationError(f"{key} must be a hostname")
            host = validate_optional_hostname(value)
            if host is None:
                result.pop(key, None)
            elif host in forbidden_hosts:
                raise ValidationError(f"{key} cannot point at {host}")
            else:
                result[key] = host
        else:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= _INT_KEYS[key]
            ):
                raise ValidationError(f"{key} must be an integer between 1 and {_INT_KEYS[key]}")
            result[key] = value
    return result


def _is_catch_all(rule: JSON) -> bool:
    return not rule.get("hostname") and not rule.get("path")


def find_ingress_rule(ingress: list[JSON], hostname: str, path: str | None) -> int:
    for i, rule in enumerate(ingress):
        if rule.get("hostname") == hostname and (rule.get("path") or None) == path:
            return i
    raise NotFoundError(f"route {hostname} not found in tunnel config")


def insert_before_catch_all(ingress: list[JSON], rule: JSON) -> list[JSON]:
    """Insert a rule before the catch-all and before any wildcard that would shadow it."""
    if not ingress or not _is_catch_all(ingress[-1]):
        raise ConflictError("tunnel config has no catch-all rule; refusing to edit it")
    host = str(rule.get("hostname", ""))
    position = len(ingress) - 1
    for i, existing in enumerate(ingress[:-1]):
        pattern = str(existing.get("hostname") or "")
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            position = i
            break
    return [*ingress[:position], rule, *ingress[position:]]


def remove_ingress_rule(ingress: list[JSON], hostname: str, path: str | None) -> list[JSON]:
    idx = find_ingress_rule(ingress, hostname, path)
    result = [r for i, r in enumerate(ingress) if i != idx]
    if not result or not _is_catch_all(result[-1]):
        raise ConflictError("removing this rule would leave the config without a catch-all")
    return result


class TunnelService:
    def __init__(
        self,
        cf: CloudflareClient,
        store: Store,
        critical: frozenset[str],
        locks: LockManager,
        policy: ServicePolicy | None = None,
    ) -> None:
        self.cf = cf
        self.store = store
        self.locks = locks
        self.waf = WafManager(cf, locks)
        self.critical = critical
        self.policy = policy or ServicePolicy()
        self._cache: _Snapshot | None = None
        self._cache_lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._cache = None

    def cached_state(self) -> State | None:
        return self._cache.state if self._cache else None

    async def _apply_blocked(self, results: dict[str, set[str]]) -> None:
        """Update block flags in the cached state from WAF write results (zone id -> hosts)."""
        async with self._cache_lock:
            snap = self._cache
            if snap is None:
                return
            names = {zid: name for name, zid in snap.zones.items()}
            blocked = {names[z]: hosts for z, hosts in results.items() if z in names}

            def flag(r: Route) -> Route:
                hosts = blocked.get(r.zone or "")
                return r if hosts is None else r.model_copy(update={"blocked": r.hostname in hosts})

            tunnels = [
                t.model_copy(update={"routes": [flag(r) for r in t.routes]})
                for t in snap.state.tunnels
            ]
            self._cache = replace(snap, state=snap.state.model_copy(update={"tunnels": tunnels}))

    async def state(self, force: bool = False) -> State:
        return (await self._snapshot(force)).state

    async def _snapshot(self, force: bool = False) -> _Snapshot:
        async with self._cache_lock:
            if self._cache:
                age = time.monotonic() - self._cache.at
                # Forced refreshes are throttled so a client cannot burn the API rate limit.
                if age < (MIN_REFRESH_INTERVAL if force else CACHE_TTL):
                    return self._cache
            self._cache = await self._discover()
            return self._cache

    async def _discover(self) -> _Snapshot:
        zones_raw, tunnels_raw = await asyncio.gather(self.cf.list_zones(), self.cf.list_tunnels())
        zones = {str(z["name"]): str(z["id"]) for z in zones_raw if z.get("name") and z.get("id")}
        tunnels_raw = [t for t in tunnels_raw if UUID_RE.fullmatch(str(t.get("id", "")))]

        async def config_of(tid: str) -> JSON | None:
            try:
                return await self.cf.get_tunnel_config(tid)
            except CloudflareError as exc:
                log.info("no remote config for tunnel %s: %s", tid, exc.message)
                return None

        configs, cnames, blocked_sets, undoable = await asyncio.gather(
            asyncio.gather(*(config_of(t["id"]) for t in tunnels_raw)),
            asyncio.gather(*(self.cf.list_cname_records(zid) for zid in zones.values())),
            asyncio.gather(*(self.waf.blocked_hosts(zid) for zid in zones.values())),
            self.store.tunnels_with_snapshots(),
        )
        blocked: set[str] = set().union(*blocked_sets)

        per_tunnel: dict[str, list[dict[str, Any]]] = {t["id"]: [] for t in tunnels_raw}
        remote: dict[str, bool] = {}
        for t, cfg in zip(tunnels_raw, configs, strict=True):
            ingress = ((cfg or {}).get("config") or {}).get("ingress") or []
            remote[t["id"]] = bool(
                cfg and cfg.get("config") is not None and cfg.get("source") != "local"
            )
            for rule in ingress:
                host = str(rule.get("hostname") or "").lower()
                if not host or not (is_hostname(host) or is_wildcard(host)):
                    continue
                per_tunnel[t["id"]].append(
                    {
                        "hostname": host,
                        "service": rule.get("service"),
                        "path": rule.get("path") or None,
                        "origin_request": rule.get("originRequest") or {},
                        "managed": remote[t["id"]],
                    }
                )

        for records in cnames:
            for rec in records:
                m = _TUNNEL_TARGET_RE.fullmatch(str(rec.get("content", "")).lower())
                host = str(rec.get("name", "")).lower()
                if not m or m.group(1) not in per_tunnel:
                    continue
                if not (is_hostname(host) or is_wildcard(host)):
                    continue
                if not any(r["hostname"] == host for r in per_tunnel[m.group(1)]):
                    per_tunnel[m.group(1)].append(
                        {
                            "hostname": host,
                            "service": None,
                            "path": None,
                            "origin_request": {},
                            "managed": False,
                        }
                    )

        tunnels: list[Tunnel] = []
        index: dict[str, set[str]] = defaultdict(set)
        for t in tunnels_raw:
            routes: list[Route] = []
            for r in per_tunnel[t["id"]]:
                host = r["hostname"]
                zone = zone_for(host, zones)
                routes.append(
                    Route(
                        hostname=host,
                        service=r["service"],
                        path=r["path"],
                        zone=zone,
                        blocked=host in blocked,
                        wildcard=host.startswith("*."),
                        critical=host in self.critical,
                        managed=r["managed"],
                        can_block=zone is not None,
                        block_disabled_reason=None if zone else "no_zone_access",
                        origin_request=r["origin_request"],
                    )
                )
                index[host].add(t["id"])
            status = str(t.get("status") or "unknown")
            tunnels.append(
                Tunnel(
                    id=t["id"],
                    name=str(t.get("name") or t["id"]),
                    status=status if status in _STATUSES else "unknown",
                    connections=len(t.get("connections") or []),
                    remote_managed=remote[t["id"]],
                    can_undo=t["id"] in undoable,
                    routes=routes,
                )
            )
        tunnels.sort(key=lambda x: x.name.lower())
        state = State(
            tunnels=tunnels,
            zones=[Zone(id=zid, name=name) for name, zid in sorted(zones.items())],
            generated_at=time.time(),
        )
        return _Snapshot(state=state, zones=zones, routes=dict(index), at=time.monotonic())

    # --- blocking -------------------------------------------------------------

    def _group_by_zone(self, hostnames: set[str], snap: _Snapshot) -> dict[str, set[str]]:
        grouped: dict[str, set[str]] = defaultdict(set)
        for host in hostnames:
            if host not in snap.routes:
                raise NotFoundError(f"{host} is not a known tunnel route")
            zone = zone_for(host, snap.zones)
            if zone is None:
                raise ValidationError(f"the API token has no access to the zone of {host}")
            grouped[snap.zones[zone]].add(host)
        return grouped

    async def set_blocked(
        self, hostname: str, blocked: bool, actor: str, confirm_critical: bool = False
    ) -> list[str]:
        host = normalize_route_hostname(hostname)
        if blocked and host in self.critical and not confirm_critical:
            raise ConfirmationRequiredError(f"{host} is critical; confirmation required")
        # Routes rarely change: a cached snapshot is enough to validate the host and find its zone.
        snap = self._cache
        if snap is None or host not in snap.routes:
            snap = await self._snapshot(force=True)
        grouped = self._group_by_zone({host}, snap)
        action = "block" if blocked else "allow"
        results: dict[str, set[str]] = {}
        try:
            for zone_id, hosts in grouped.items():
                kw = {"block": hosts} if blocked else {"allow": hosts}
                results[zone_id] = await self.waf.update(zone_id, **kw)
        except CloudflareError, WafError:
            self.invalidate()
            await self.store.audit(actor, action, host, "error")
            raise
        await self._apply_blocked(results)
        await self.store.audit(actor, action, host, "ok")
        return sorted(set().union(*results.values()))

    async def _block_routes(
        self, routes: list[Route], actor: str, action: str, target: str
    ) -> BlockResult:
        """Block every route it can, keep going past failing zones, and report what is left open."""
        snap = await self._snapshot(force=True)
        skipped = sorted({r.hostname for r in routes if not r.can_block})
        grouped = self._group_by_zone({r.hostname for r in routes if r.can_block}, snap)
        blocked: set[str] = set()
        failed: list[str] = []
        results: dict[str, set[str]] = {}
        for zone_id, hosts in grouped.items():
            try:
                results[zone_id] = await self.waf.update(zone_id, block=hosts)
                blocked |= results[zone_id] & hosts
            except (CloudflareError, WafError) as exc:
                log.error("blocking failed in zone %s: %s", zone_id, exc)
                failed.extend(sorted(hosts))
        if failed:
            self.invalidate()
        else:
            await self._apply_blocked(results)
        outcome = "error" if failed else ("partial" if skipped else "ok")
        await self.store.audit(
            actor, action, target, outcome, blocked=sorted(blocked), failed=failed, skipped=skipped
        )
        if failed:
            raise PartialBlockError(sorted(blocked), failed, skipped)
        return BlockResult(blocked=sorted(blocked), skipped=skipped)

    async def block_tunnel(self, tunnel_id: str, actor: str) -> BlockResult:
        validate_tunnel_id(tunnel_id)
        snap = await self._snapshot(force=True)
        tunnel = next((t for t in snap.state.tunnels if t.id == tunnel_id), None)
        if tunnel is None:
            raise NotFoundError("tunnel not found")
        return await self._block_routes(tunnel.routes, actor, "block-tunnel", tunnel.name)

    async def kill_all(self, actor: str) -> BlockResult:
        snap = await self._snapshot(force=True)
        routes = [r for t in snap.state.tunnels for r in t.routes]
        return await self._block_routes(routes, actor, "kill-all", "*")

    async def unblock_all(self, actor: str) -> None:
        snap = await self._snapshot(force=True)
        failed: list[str] = []
        for zone_id in sorted(set(snap.zones.values())):
            try:
                current = await self.waf.blocked_hosts(zone_id)
                if current:
                    await self.waf.update(zone_id, allow=current)
            except (CloudflareError, WafError) as exc:
                log.error("unblocking failed in zone %s: %s", zone_id, exc)
                failed.append(zone_id)
        self.invalidate()
        await self.store.audit(
            actor, "unblock-all", "*", "error" if failed else "ok", failed=failed
        )
        if failed:
            raise PartialBlockError([], failed, [])

    # --- routes ---------------------------------------------------------------

    async def _remote_config(self, tunnel_id: str) -> JSON:
        cfg = await self.cf.get_tunnel_config(tunnel_id)
        config = cfg.get("config")
        if cfg.get("source") == "local" or not isinstance(config, dict):
            raise ConflictError("this tunnel is locally managed; its routes cannot be edited here")
        return config

    async def clone_route(self, tunnel_id: str, req: CloneRequest, actor: str) -> str:
        validate_tunnel_id(tunnel_id)
        source_host = normalize_route_hostname(req.source_hostname)
        source_path = validate_path(req.source_path)
        service = self.policy.check(validate_service(req.service))
        path = validate_path(req.path)
        snap = await self._snapshot(force=True)
        zone_name = next((n for n, zid in snap.zones.items() if zid == req.zone_id), None)
        if zone_name is None:
            raise ValidationError("zone is not available to the API token")
        new_host = build_hostname(req.subdomain, zone_name)
        if not hostname_in_zone(new_host, zone_name):
            raise ValidationError("hostname is outside the selected zone")
        if new_host in snap.routes:
            raise ConflictError(f"{new_host} is already used by a tunnel route")
        if await self.cf.list_records_by_name(req.zone_id, new_host):
            raise ConflictError(f"a DNS record for {new_host} already exists")

        async with self.locks.hold(f"tunnel-{tunnel_id}"):
            config = await self._remote_config(tunnel_id)
            ingress: list[JSON] = list(config.get("ingress") or [])
            source = ingress[find_ingress_rule(ingress, source_host, source_path)]
            rule: JSON = {"hostname": new_host, "service": service}
            if path:
                rule["path"] = path
            origin = apply_origin_overrides(
                source.get("originRequest") or {}, req.origin_request, self.policy.forbidden_hosts
            )
            if origin:
                rule["originRequest"] = origin
            new_config = {**config, "ingress": insert_before_catch_all(ingress, rule)}

            # Block first so the route is never reachable before the user allows it.
            if req.create_blocked:
                await self.waf.update(req.zone_id, block={new_host})
            snapshot_id = await self.store.save_snapshot(
                tunnel_id, actor, f"clone {new_host}", config
            )
            try:
                await self.cf.put_tunnel_config(tunnel_id, new_config)
            except CloudflareError:
                await self._abort_clone(snapshot_id, req, new_host, actor, tunnel_id, None)
                raise
            try:
                record = await self.cf.create_cname(
                    req.zone_id, new_host, f"{tunnel_id}.cfargotunnel.com"
                )
            except CloudflareError:
                log.warning("DNS creation failed for %s; rolling back tunnel config", new_host)
                await self._abort_clone(snapshot_id, req, new_host, actor, tunnel_id, config)
                raise
            await self.store.update_snapshot_meta(
                snapshot_id,
                {
                    "post": new_config,
                    "dns_created": [{"zone_id": req.zone_id, "record_id": str(record.get("id"))}],
                },
            )
        self.invalidate()
        await self.store.audit(
            actor,
            "clone",
            new_host,
            "ok",
            tunnel=tunnel_id,
            source=source_host,
            service=service,
            blocked=req.create_blocked,
        )
        return new_host

    async def _abort_clone(  # noqa: PLR0917
        self,
        snapshot_id: int,
        req: CloneRequest,
        host: str,
        actor: str,
        tunnel_id: str,
        restore: JSON | None,
    ) -> None:
        problems: list[str] = []
        if restore is not None:
            try:
                await self.cf.put_tunnel_config(tunnel_id, restore)
            except CloudflareError as exc:
                problems.append(f"config restore failed: {exc.message}")
        if not problems:
            await self.store.delete_snapshot(snapshot_id)
        # A leftover block entry is harmless; it is kept if the rollback above failed.
        if req.create_blocked and not problems:
            try:
                await self.waf.update(req.zone_id, allow={host})
            except (CloudflareError, WafError) as exc:
                problems.append(f"unblock failed: {exc}")
        self.invalidate()
        await self.store.audit(
            actor,
            "clone",
            host,
            "rolled-back" if not problems else "rollback-failed",
            tunnel=tunnel_id,
            problems=problems,
        )

    async def remove_route(
        self, tunnel_id: str, hostname: str, path: str | None, confirm: str, actor: str
    ) -> None:
        validate_tunnel_id(tunnel_id)
        host = normalize_route_hostname(hostname)
        path = validate_path(path)
        if confirm.strip().lower() != host:
            raise ConfirmationRequiredError("type the hostname to confirm removal")
        snap = await self._snapshot(force=True)
        meta: dict[str, Any] = {"dns_deleted": [], "waf_unblocked": None}
        async with self.locks.hold(f"tunnel-{tunnel_id}"):
            config = await self._remote_config(tunnel_id)
            ingress: list[JSON] = list(config.get("ingress") or [])
            new_ingress = remove_ingress_rule(ingress, host, path)
            new_config = {**config, "ingress": new_ingress}
            snapshot_id = await self.store.save_snapshot(tunnel_id, actor, f"remove {host}", config)
            try:
                await self.cf.put_tunnel_config(tunnel_id, new_config)
            except CloudflareError:
                await self.store.delete_snapshot(snapshot_id)
                await self.store.audit(actor, "remove", host, "error", tunnel=tunnel_id)
                raise
            meta["post"] = new_config
            try:
                still_here = any(r.get("hostname") == host for r in new_ingress)
                elsewhere = snap.routes.get(host, set()) - {tunnel_id}
                zone = zone_for(host, snap.zones)
                if not still_here and zone is not None:
                    zone_id = snap.zones[zone]
                    target = f"{tunnel_id}.cfargotunnel.com"
                    remaining = False
                    for rec in await self.cf.list_records_by_name(zone_id, host):
                        if (
                            rec.get("type") == "CNAME"
                            and str(rec.get("content", "")).lower() == target
                        ):
                            await self.cf.delete_dns_record(zone_id, str(rec["id"]))
                            meta["dns_deleted"].append(
                                {
                                    "zone_id": zone_id,
                                    "name": host,
                                    "content": target,
                                    "proxied": bool(rec.get("proxied", True)),
                                }
                            )
                        else:
                            remaining = True
                    # Only drop the block when no other tunnel or record still serves the host.
                    if (
                        not elsewhere
                        and not remaining
                        and host in await self.waf.blocked_hosts(zone_id)
                    ):
                        await self.waf.update(zone_id, allow={host})
                        meta["waf_unblocked"] = zone_id
            finally:
                await self.store.update_snapshot_meta(snapshot_id, meta)
                self.invalidate()
        await self.store.audit(
            actor,
            "remove",
            host,
            "ok",
            tunnel=tunnel_id,
            path=path,
            dns_removed=len(meta["dns_deleted"]),
            unblocked=bool(meta["waf_unblocked"]),
        )

    async def undo(self, tunnel_id: str, actor: str) -> None:
        """Restore the config saved before the last change and revert its DNS and WAF effects."""
        validate_tunnel_id(tunnel_id)
        async with self.locks.hold(f"tunnel-{tunnel_id}"):
            latest = await self.store.latest_snapshot(tunnel_id)
            if latest is None:
                raise NotFoundError("nothing to undo for this tunnel")
            snapshot_id, config, meta = latest
            current = await self._remote_config(tunnel_id)
            post = meta.get("post")
            if post is not None and current.get("ingress") != post.get("ingress"):
                raise ConflictError(
                    "the tunnel config changed after this snapshot; undo refused to avoid "
                    "overwriting newer edits"
                )
            problems: list[str] = []
            zone_id = meta.get("waf_unblocked")
            if zone_id:
                # The removed route was blocked before; block it again before it comes back.
                now_hosts = {r.get("hostname") for r in current.get("ingress", [])}
                removed = {
                    str(r["hostname"])
                    for r in config.get("ingress", [])
                    if r.get("hostname") and r.get("hostname") not in now_hosts
                }
                try:
                    await self.waf.update(str(zone_id), block=removed)
                except (CloudflareError, WafError) as exc:
                    raise ConflictError(
                        f"could not re-block the route before restoring it: {exc}"
                    ) from exc
            await self.cf.put_tunnel_config(tunnel_id, config)
            await self.store.delete_snapshot(snapshot_id)
            for rec in meta.get("dns_created", []):
                try:
                    await self.cf.delete_dns_record(str(rec["zone_id"]), str(rec["record_id"]))
                except CloudflareError as exc:
                    problems.append(f"delete DNS {rec['record_id']}: {exc.message}")
            for rec in meta.get("dns_deleted", []):
                try:
                    await self.cf.create_cname(
                        str(rec["zone_id"]), str(rec["name"]), str(rec["content"])
                    )
                except CloudflareError as exc:
                    problems.append(f"recreate DNS {rec['name']}: {exc.message}")
        self.invalidate()
        await self.store.audit(
            actor,
            "undo",
            tunnel_id,
            "ok" if not problems else "partial",
            snapshot=snapshot_id,
            problems=problems,
        )
        if problems:
            raise ConflictError(
                "config restored, but some DNS or block changes failed: " + "; ".join(problems)
            )


__all__ = [
    "BlockResult",
    "ConfirmationRequiredError",
    "ConflictError",
    "NotFoundError",
    "PartialBlockError",
    "TunnelService",
    "TunnelStatus",
    "apply_origin_overrides",
    "find_ingress_rule",
    "insert_before_catch_all",
    "remove_ingress_rule",
    "validate_tunnel_id",
]
