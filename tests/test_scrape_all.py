import argparse
from pathlib import Path

import ms_data.scraping.scrape_msdata as sm


class _FakeClient:
    pass


class _FakeCacheHTTP:
    def __init__(self, client, config):
        self.client = client
        self.config = config

    def get(self, url: str):
        return "<html></html>", {"semantic_changed": True}


def test_cmd_all_forwards_detail_options(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sm, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(sm, "CacheHTTP", _FakeCacheHTTP)
    monkeypatch.setattr(sm, "parse_index", lambda html: [])

    def fake_cmd_details(args: argparse.Namespace) -> int:
        captured["input"] = args.input
        captured["out"] = args.out
        captured["rate"] = args.rate
        captured["limit"] = args.limit
        captured["ttl"] = args.ttl
        captured["no_network"] = args.no_network
        captured["force"] = args.force
        captured["changed_only"] = args.changed_only
        captured["detail_fetch_state_out"] = args.detail_fetch_state_out
        return 0

    monkeypatch.setattr(sm, "cmd_details", fake_cmd_details)

    out_path = tmp_path / "details.jsonl"
    rc = sm.cmd_all(
        argparse.Namespace(
            out=str(out_path),
            rate=2.0,
            limit=1,
            ttl="1d",
            no_network=True,
            force=True,
            changed_only=True,
            detail_fetch_state_out="cache/detail_fetch_state.json",
        )
    )

    assert rc == 0
    assert captured == {
        "input": str(Path("cache/index.json")),
        "out": str(out_path),
        "rate": 2.0,
        "limit": 1,
        "ttl": "1d",
        "no_network": True,
        "force": True,
        "changed_only": True,
        "detail_fetch_state_out": "cache/detail_fetch_state.json",
    }
    assert Path("cache/index.json").exists()
