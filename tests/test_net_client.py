"""atwiki 用 HTTP クライアントファクトリのテスト。"""

from __future__ import annotations

import builtins
import functools
import sys
from types import ModuleType

import httpx
import pytest

from ms_data.net.client import get_browser_client, get_scraper_client

SCRAPER_USER_AGENT = "msdata-scraper/0.1 (+https://github.com/; contact=local)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116 Safari/537.36"
)


class FakeCloudscraper:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.closed = False

    def request(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("テスト中に HTTP リクエストを送信してはいけない")

    def close(self) -> None:
        self.closed = True


def _install_fake_cloudscraper(
    monkeypatch: pytest.MonkeyPatch,
) -> FakeCloudscraper:
    scraper = FakeCloudscraper()
    module = ModuleType("cloudscraper")
    module.create_scraper = lambda: scraper  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloudscraper", module)
    return scraper


def _assert_timeout(timeout: httpx.Timeout, expected: float) -> None:
    assert timeout.connect == expected
    assert timeout.read == expected
    assert timeout.write == expected
    assert timeout.pool == expected


@pytest.mark.parametrize(
    ("env_value", "expected_backend"),
    [("httpx", "httpx"), ("cloudscraper", "cloudscraper"), (None, "cloudscraper")],
    ids=["explicit-httpx", "explicit-cloudscraper", "default-cloudscraper"],
)
def test_get_scraper_client_selects_backend(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str | None,
    expected_backend: str,
) -> None:
    fake_scraper = _install_fake_cloudscraper(monkeypatch)
    if env_value is None:
        monkeypatch.delenv("MSDATA_HTTP_CLIENT", raising=False)
    else:
        monkeypatch.setenv("MSDATA_HTTP_CLIENT", env_value)

    client = get_scraper_client(timeout=12.5)
    try:
        if expected_backend == "cloudscraper":
            assert client is fake_scraper
            assert fake_scraper.headers["User-Agent"] == SCRAPER_USER_AGENT
            assert isinstance(fake_scraper.request, functools.partial)
            assert fake_scraper.request.keywords == {"timeout": 12.5}
        else:
            assert isinstance(client, httpx.Client)
            assert client.headers["User-Agent"] == SCRAPER_USER_AGENT
            assert client.follow_redirects is True
            _assert_timeout(client.timeout, 12.5)
    finally:
        client.close()

    if isinstance(client, httpx.Client):
        assert client.is_closed
    else:
        assert fake_scraper.closed


def test_get_scraper_client_falls_back_when_cloudscraper_import_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MSDATA_HTTP_CLIENT", "cloudscraper")
    original_import = builtins.__import__

    def fail_cloudscraper_import(
        name: str,
        globals_: dict[str, object] | None = None,
        locals_: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "cloudscraper":
            raise ImportError("cloudscraper unavailable in test")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_cloudscraper_import)

    client = get_scraper_client(timeout=7.0)
    try:
        assert isinstance(client, httpx.Client)
        assert client.headers["User-Agent"] == SCRAPER_USER_AGENT
        assert client.follow_redirects is True
        _assert_timeout(client.timeout, 7.0)
        assert "cloudscraper unavailable, fallback to httpx" in capsys.readouterr().err
    finally:
        client.close()

    assert client.is_closed


def test_get_browser_client_configures_browser_headers_and_options() -> None:
    client = get_browser_client(timeout=9.0)
    try:
        assert client.headers["User-Agent"] == BROWSER_USER_AGENT
        assert client.headers["Accept"] == (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        )
        assert client.headers["Accept-Language"] == "ja,en-US;q=0.7,en;q=0.3"
        assert client.follow_redirects is True
        _assert_timeout(client.timeout, 9.0)
    finally:
        client.close()

    assert client.is_closed
