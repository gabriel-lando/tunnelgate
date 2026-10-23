"""Command line entry point: web server and break-glass commands."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from pydantic import ValidationError as SettingsError

from tunnelgate.cloudflare import CloudflareClient, CloudflareError
from tunnelgate.config import CloudflareSettings
from tunnelgate.locks import LockManager
from tunnelgate.service import PartialBlockError, TunnelService
from tunnelgate.store import Store

# Inside the container the app must listen on all interfaces; no port is published.
_DEFAULT_HOST = "0.0.0.0"  # noqa: S104  # nosec B104


class _HealthcheckFilter(logging.Filter):
    """Drop successful /healthz access lines (the container healthcheck runs every 30 s)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            path, status = args[2], args[4]
            return not (path == "/healthz" and isinstance(status, int) and status < 400)
        return True


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("uvicorn.access").addFilter(_HealthcheckFilter())


def _serve(host: str, port: int) -> int:
    import uvicorn

    from tunnelgate.app import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=False,
        server_header=False,
        log_config=None,
        access_log=True,
    )
    return 0


async def _break_glass(command: str) -> int:
    settings = CloudflareSettings()
    cf = CloudflareClient(
        settings.cf_api_token.get_secret_value(), settings.cf_account_id, settings.cf_api_base
    )
    store = Store(settings.data_dir)
    svc = TunnelService(
        cf, store, frozenset(settings.critical_hosts), LockManager(settings.data_dir)
    )
    try:
        if command == "block-all":
            result = await svc.kill_all("cli")
            print(f"Blocked {len(result.blocked)} route(s).")
            if result.skipped:
                print("NOT BLOCKED (no zone access for the token):", file=sys.stderr)
                for host in result.skipped:
                    print(f"  {host}", file=sys.stderr)
                return 3
        elif command == "unblock-all":
            await svc.unblock_all("cli")
            print("Unblocked all routes managed by Tunnelgate.")
        else:
            state = await svc.state(force=True)
            for tunnel in state.tunnels:
                print(f"{tunnel.name} [{tunnel.status}, {tunnel.connections} connection(s)]")
                for route in tunnel.routes:
                    flag = "BLOCKED" if route.blocked else "open"
                    print(f"  {flag:8} {route.hostname} -> {route.service or '?'}")
        return 0
    except PartialBlockError as exc:
        print(f"Blocked {len(exc.blocked)} route(s), but these FAILED:", file=sys.stderr)
        for host in [*exc.failed, *exc.skipped]:
            print(f"  {host}", file=sys.stderr)
        return 3
    except CloudflareError as exc:
        print(f"Cloudflare API error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        await cf.aclose()
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tunnelgate")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the web server")
    serve.add_argument("--host", default=_DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("status", help="list tunnels, routes and block status")
    sub.add_parser("block-all", help="block every route (break-glass)")
    sub.add_parser("unblock-all", help="remove every route from the block list (break-glass)")
    args = parser.parse_args(argv)
    _setup_logging()
    try:
        if args.command in (None, "serve"):
            return _serve(getattr(args, "host", _DEFAULT_HOST), getattr(args, "port", 8000))
        return asyncio.run(_break_glass(args.command))
    except SettingsError as exc:
        missing = sorted({str(e["loc"][0]).upper() for e in exc.errors() if e.get("loc")})
        print(f"Invalid configuration: {', '.join(missing)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
