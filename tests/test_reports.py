"""Tests for `tl reports create --config[-file]` and `tl reports update`."""

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from tl_cli.commands.reports import _parse_config_arg, app

runner = CliRunner()


# ---------------------------------------------------------------------------
# _parse_config_arg
# ---------------------------------------------------------------------------


class TestParseConfigArg:
    def test_valid_object_returns_dict(self) -> None:
        result = _parse_config_arg('{"report_title": "Test", "report_type": 3}')
        assert result == {"report_title": "Test", "report_type": 3}

    def test_invalid_json_exits(self) -> None:
        with pytest.raises(typer.Exit) as excinfo:
            _parse_config_arg('{not json')
        assert excinfo.value.exit_code == 1

    def test_non_object_exits(self) -> None:
        # JSON arrays / strings / numbers are valid JSON but not the object the
        # endpoint accepts.
        with pytest.raises(typer.Exit) as excinfo:
            _parse_config_arg('[1, 2, 3]')
        assert excinfo.value.exit_code == 1


# ---------------------------------------------------------------------------
# tl reports create — argument validation
# ---------------------------------------------------------------------------


class TestCreateArgValidation:
    def test_no_prompt_and_no_config_rejected(self) -> None:
        result = runner.invoke(app, ["create"])
        assert result.exit_code == 1
        msg = (result.stderr or result.output).lower()
        assert "exactly one" in msg and "config" in msg

    def test_both_prompt_and_config_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["create", "gaming channels", "--config", '{"report_title": "x", "report_type": 3}'],
        )
        assert result.exit_code == 1
        assert "exactly one" in (result.stderr or result.output).lower()

    def test_both_config_and_config_file_rejected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "c.json"
        cfg.write_text('{"report_title": "x", "report_type": 3}', encoding="utf-8")
        result = runner.invoke(
            app,
            ["create", "--config", '{"report_title": "y"}', "--config-file", str(cfg)],
        )
        assert result.exit_code == 1
        assert "exactly one" in (result.stderr or result.output).lower()

    def test_both_prompt_and_config_file_rejected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "c.json"
        cfg.write_text('{"report_title": "x", "report_type": 3}', encoding="utf-8")
        result = runner.invoke(app, ["create", "gaming", "--config-file", str(cfg)])
        assert result.exit_code == 1
        assert "exactly one" in (result.stderr or result.output).lower()

    def test_config_invalid_json_rejected(self) -> None:
        result = runner.invoke(app, ["create", "--config", "{not json", "--yes"])
        assert result.exit_code == 1
        assert "valid json" in (result.stderr or result.output).lower()

    def test_config_non_object_rejected(self) -> None:
        result = runner.invoke(app, ["create", "--config", "[1,2,3]", "--yes"])
        assert result.exit_code == 1
        assert "json object" in (result.stderr or result.output).lower()

    def test_config_file_missing_path_rejected(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(app, ["create", "--config-file", str(missing), "--yes"])
        assert result.exit_code == 1
        assert "could not read" in (result.stderr or result.output).lower()

    def test_config_file_invalid_json_rejected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "broken.json"
        cfg.write_text("{not json", encoding="utf-8")
        result = runner.invoke(app, ["create", "--config-file", str(cfg), "--yes"])
        assert result.exit_code == 1
        assert "valid json" in (result.stderr or result.output).lower()

    def test_config_file_handles_apostrophes(self, tmp_path: Path) -> None:
        # The whole point of --config-file: shell-quoting woes don't apply when
        # the JSON lives in a file. A title with an apostrophe must round-trip.
        cfg = tmp_path / "quote.json"
        cfg.write_text(
            json.dumps({"report_title": "McDonald's gaming pipeline", "report_type": 3}),
            encoding="utf-8",
        )
        # We don't have a live API to POST to in unit tests, so we stop short of
        # a successful save. But the parse step should not blow up on the
        # apostrophe — what we're guarding against is "valid json" complaints.
        # Use --json so the command exits cleanly after preview without
        # prompting (no confirm + no save).
        result = runner.invoke(
            app, ["create", "--config-file", str(cfg), "--json"]
        )
        # Command exits 0 after preview when --json is set without --yes.
        assert result.exit_code == 0
        assert "McDonald's" in (result.stdout or result.output)


# ---------------------------------------------------------------------------
# tl reports update — argument validation
# ---------------------------------------------------------------------------


class TestUpdateArgValidation:
    def test_invalid_json_rejected(self) -> None:
        result = runner.invoke(app, ["update", "12345", "{not json"])
        assert result.exit_code == 1
        assert "json object" in (result.stderr or result.output).lower()

    def test_non_object_rejected(self) -> None:
        result = runner.invoke(app, ["update", "12345", '"just a string"'])
        assert result.exit_code == 1
        assert "json object" in (result.stderr or result.output).lower()
