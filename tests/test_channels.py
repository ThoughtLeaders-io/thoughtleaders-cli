"""Tests for `tl channels show` TL analysis-page deep-link injection."""

import pytest

from tl_cli.commands.channels import _inject_tl_url
from tl_cli.config import Config


class TestAppUrl:
    def test_joins_root_path(self) -> None:
        c = Config(api_url="https://app.thoughtleaders.io")
        assert c.app_url("channelid/824836") == "https://app.thoughtleaders.io/channelid/824836"

    def test_collapses_duplicate_slashes(self) -> None:
        # Trailing slash on the base and leading slash on the path must not
        # produce a `//` in the joined URL.
        c = Config(api_url="https://app.thoughtleaders.io/")
        assert c.app_url("/channelid/5") == "https://app.thoughtleaders.io/channelid/5"

    def test_respects_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Links must follow whichever environment the CLI is pointed at.
        monkeypatch.setenv("TL_API_URL", "https://staging.example.com")
        assert Config().app_url("channelid/7") == "https://staging.example.com/channelid/7"


class TestInjectTlUrl:
    def test_uses_channelid_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TL_API_URL", raising=False)
        rec = _inject_tl_url({"channel_id": 824836, "name": "Josean Martinez"})
        assert rec["tl_url"] == "https://app.thoughtleaders.io/channelid/824836"

    def test_falls_back_to_id_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Before the show command renames `id` -> `channel_id`, the raw record
        # only carries `id`; the helper must handle both.
        monkeypatch.delenv("TL_API_URL", raising=False)
        rec = _inject_tl_url({"id": 12345})
        assert rec["tl_url"] == "https://app.thoughtleaders.io/channelid/12345"

    def test_noop_without_id(self) -> None:
        rec = _inject_tl_url({"name": "x"})
        assert "tl_url" not in rec
