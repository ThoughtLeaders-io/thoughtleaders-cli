"""Tests for brands command validation and result formatting."""

import pytest
import typer

from tl_cli.commands.brands import _format_results, _validate_list_args, _validate_show_args


class TestFormatResults:
    def test_truncates_latest_date(self):
        results = [{"latest_date": "2026-04-13T10:00:00", "channel": "test"}]
        formatted = _format_results(results)
        assert formatted[0]["latest_date"] == "2026-04-13"

    def test_handles_missing_date(self):
        results = [{"channel": "test"}]
        formatted = _format_results(results)
        assert "latest_date" not in formatted[0]

    def test_handles_none_date(self):
        results = [{"latest_date": None, "channel": "test"}]
        formatted = _format_results(results)
        assert formatted[0]["latest_date"] is None

    def test_handles_date_only(self):
        results = [{"latest_date": "2026-04-13", "channel": "test"}]
        formatted = _format_results(results)
        assert formatted[0]["latest_date"] == "2026-04-13"

    def test_multiple_results(self):
        results = [
            {"latest_date": "2026-04-13T10:00:00"},
            {"latest_date": "2026-03-01T08:30:00"},
        ]
        formatted = _format_results(results)
        assert formatted[0]["latest_date"] == "2026-04-13"
        assert formatted[1]["latest_date"] == "2026-03-01"

    def test_empty_results(self):
        assert _format_results([]) == []


class TestValidateShowArgs:
    def test_valid_args(self):
        # Should not raise
        _validate_show_args("Nike", 50, 0, None)

    def test_valid_args_with_channel(self):
        _validate_show_args("Nike", 50, 0, 12345)

    def test_empty_query_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("", 50, 0, None)

    def test_whitespace_query_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("   ", 50, 0, None)

    def test_limit_zero_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("Nike", 0, 0, None)

    def test_limit_negative_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("Nike", -1, 0, None)

    def test_limit_over_max_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("Nike", 201, 0, None)

    def test_limit_boundary_values(self):
        _validate_show_args("Nike", 1, 0, None)
        _validate_show_args("Nike", 200, 0, None)

    def test_offset_negative_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("Nike", 50, -1, None)

    def test_channel_zero_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("Nike", 50, 0, 0)

    def test_channel_negative_exits(self):
        with pytest.raises(typer.Exit):
            _validate_show_args("Nike", 50, 0, -1)


class TestValidateListArgs:
    def test_valid_args(self):
        _validate_list_args(50, 0)

    def test_limit_zero_exits(self):
        with pytest.raises(typer.Exit):
            _validate_list_args(0, 0)

    def test_limit_over_max_exits(self):
        with pytest.raises(typer.Exit):
            _validate_list_args(201, 0)

    def test_offset_negative_exits(self):
        with pytest.raises(typer.Exit):
            _validate_list_args(50, -1)

    def test_limit_boundary_values(self):
        _validate_list_args(1, 0)
        _validate_list_args(200, 0)
