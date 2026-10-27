from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.conftest import ACCOUNT, FakeCloudflare, make_fake
from tunnelgate import cli


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeCloudflare:
    fake = make_fake()
    monkeypatch.setenv("CF_API_TOKEN", "t")
    monkeypatch.setenv("CF_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("TUNNELGATE_DATA_DIR", str(tmp_path))
    real = cli.CloudflareClient

    def patched(token: str, account: str, base: str) -> object:
        return real(token, account, base, transport=httpx.MockTransport(fake.handler))

    monkeypatch.setattr(cli, "CloudflareClient", patched)
    return fake


def test_block_all_and_unblock_all(
    fake: FakeCloudflare, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["block-all"]) == 3  # other.elsewhere.org cannot be blocked
    captured = capsys.readouterr()
    assert "Blocked 5 route(s)" in captured.out
    assert "other.elsewhere.org" in captured.err
    rule = fake.rule()
    assert rule is not None and rule["enabled"] is True
    assert cli.main(["unblock-all"]) == 0
    assert fake.rule()["enabled"] is False  # type: ignore[index]


def test_block_all_reports_failed_zone(
    fake: FakeCloudflare, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import ZONE_ID, fail

    entry = rf"/zones/{ZONE_ID}/rulesets/phases/http_request_firewall_custom/entrypoint"
    fake.fail_next[("PUT", entry)] = fail(403, 10000, "denied")
    assert cli.main(["block-all"]) == 3
    assert "FAILED" in capsys.readouterr().err


def test_status_lists_routes(fake: FakeCloudflare, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "apps [healthy, 2 replica(s), v2026.10.0, v2026.9.1]" in out
    assert "media [down, 0 replica(s), no version]" in out
    assert "open     git.example.com -> http://gitea:3000" in out


def test_missing_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    assert cli.main(["status"]) == 2
    assert "CF_API_TOKEN" in capsys.readouterr().err


def test_cloudflare_error_exit_code(
    fake: FakeCloudflare, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import fail

    fake.fail_next[("GET", "/zones")] = fail(403, 10000, "Authentication error")
    assert cli.main(["status"]) == 1
    assert "Authentication error" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("path", "status", "kept"),
    [
        ("/healthz", 200, False),
        ("/healthz", 503, True),
        ("/api/state", 200, True),
    ],
)
def test_healthcheck_access_lines_are_dropped(path: str, status: int, kept: bool) -> None:
    import logging

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", path, "1.1", status),
        None,
    )
    assert cli._HealthcheckFilter().filter(record) is kept


def test_hash_password_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    from tunnelgate.passwords import verify_password

    monkeypatch.setattr("sys.stdin", io.StringIO(" my pass \n"))
    assert cli.main(["hash-password"]) == 0
    captured = capsys.readouterr()
    assert verify_password(" my pass ", captured.out.strip())
    assert "Reading the password from stdin" in captured.err
    assert cli.main(["hash-password", "senha forte"]) == 0
    assert verify_password("senha forte", capsys.readouterr().out.strip())
    assert cli.main(["hash-password", ""]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert cli.main(["hash-password"]) == 1


def test_hash_password_interactive_mismatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    answers = iter(["one", "two"])
    stdin = io.StringIO()
    stdin.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.main(["hash-password"]) == 1
    assert "do not match" in capsys.readouterr().err


def test_missing_sign_in_method_is_explained(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from tests.conftest import APP

    for k in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "BASIC_AUTH_USERNAME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CF_API_TOKEN", "t")
    monkeypatch.setenv("CF_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("APP_URL", APP)
    monkeypatch.setenv("TUNNELGATE_DATA_DIR", str(tmp_path))
    assert cli.main(["serve"]) == 2
    assert "configure OIDC" in capsys.readouterr().err
