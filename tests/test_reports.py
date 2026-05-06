"""Tests for `tl reports create --config` and `tl reports update`."""

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
        assert "either" in (result.stderr or result.output).lower() and "config" in (result.stderr or result.output).lower()

    def test_both_prompt_and_config_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["create", "gaming channels", "--config", '{"report_title": "x", "report_type": 3}'],
        )
        assert result.exit_code == 1
        assert "either" in (result.stderr or result.output).lower()

    def test_config_invalid_json_rejected(self) -> None:
        result = runner.invoke(app, ["create", "--config", "{not json", "--yes"])
        assert result.exit_code == 1
        assert "valid json" in (result.stderr or result.output).lower()

    def test_config_non_object_rejected(self) -> None:
        result = runner.invoke(app, ["create", "--config", "[1,2,3]", "--yes"])
        assert result.exit_code == 1
        assert "json object" in (result.stderr or result.output).lower()


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
