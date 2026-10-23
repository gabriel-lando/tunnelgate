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
    assert "apps [healthy, 4 connection(s)]" in out
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
