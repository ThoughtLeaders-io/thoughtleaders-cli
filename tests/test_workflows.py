"""Tests for `tl workflow create` blueprint validation.

These cover the input-validation paths that exit before any HTTP call, so no
client mocking is needed. The command is invoked through the top-level app
(`tl workflow create ...`) — the real invocation path — because a single-command
Typer collapses its lone command when invoked in isolation.
"""

from pathlib import Path

from typer.testing import CliRunner

from tl_cli.main import app

runner = CliRunner()


class TestWorkflowCreateValidation:
    def test_no_source_rejected(self) -> None:
        result = runner.invoke(app, ["workflow", "create"])
        assert result.exit_code == 2
        assert "exactly one" in (result.stderr or result.output).lower()

    def test_both_file_and_config_rejected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "bp.json"
        cfg.write_text('{"name": "X", "report_type": 3, "steps": [{}]}', encoding="utf-8")
        result = runner.invoke(
            app, ["workflow", "create", "--file", str(cfg), "--config", "{}"]
        )
        assert result.exit_code == 2
        assert "exactly one" in (result.stderr or result.output).lower()

    def test_invalid_json_rejected(self) -> None:
        result = runner.invoke(app, ["workflow", "create", "--config", "{not json"])
        assert result.exit_code == 1
        assert "blueprint json" in (result.stderr or result.output).lower()

    def test_non_object_blueprint_rejected(self) -> None:
        result = runner.invoke(app, ["workflow", "create", "--config", "[1, 2, 3]"])
        assert result.exit_code == 1
        assert "json object" in (result.stderr or result.output).lower()

    def test_missing_name_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["workflow", "create", "--config", '{"report_type": 3, "steps": [{"title": "S"}]}'],
        )
        assert result.exit_code == 1
        assert "name" in (result.stderr or result.output).lower()

    def test_bad_report_type_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["workflow", "create", "--config", '{"name": "X", "report_type": 5, "steps": [{"title": "S"}]}'],
        )
        assert result.exit_code == 1
        assert "report_type" in (result.stderr or result.output).lower()

    def test_empty_steps_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["workflow", "create", "--config", '{"name": "X", "report_type": 3, "steps": []}'],
        )
        assert result.exit_code == 1
        assert "steps" in (result.stderr or result.output).lower()

    def test_non_dict_steps_rejected_cleanly(self) -> None:
        # A hand-written blueprint that lists stage names as bare strings instead
        # of objects. This must fail loud with a clean message — not crash with an
        # AttributeError in the confirmation preview (the interactive path, no
        # --yes, is where the preview loop runs).
        result = runner.invoke(
            app,
            ["workflow", "create", "--config", '{"name": "X", "report_type": 3, "steps": ["Sourced", "Qualify"]}'],
            input="y\n",
        )
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "json object" in (result.stderr or result.output).lower()
