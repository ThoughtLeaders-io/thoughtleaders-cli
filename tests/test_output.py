"""Tests for output formatting."""

import csv
import io
import json
import math
from contextlib import redirect_stdout

from tl_cli.output.formatter import (
    _csv_cell,
    _dump_json,
    _format_numeric,
    _output_csv,
    _output_markdown,
    _sanitize_for_json,
    detect_format,
)


class TestDetectFormat:
    def test_json_flag(self):
        assert detect_format(json_flag=True, csv_flag=False, md_flag=False) == "json"

    def test_csv_flag(self):
        assert detect_format(json_flag=False, csv_flag=True, md_flag=False) == "csv"

    def test_md_flag(self):
        assert detect_format(json_flag=False, csv_flag=False, md_flag=True) == "md"

    def test_no_flags_non_tty(self):
        # When piped (non-TTY), default to JSON — can't test TTY easily
        result = detect_format(json_flag=False, csv_flag=False, md_flag=False)
        assert result in ("table", "json")  # Depends on test runner TTY


class TestSanitizeForJson:
    def test_finite_float_passes_through(self):
        assert _sanitize_for_json(1.5) == 1.5

    def test_int_passes_through(self):
        assert _sanitize_for_json(42) == 42

    def test_none_passes_through(self):
        assert _sanitize_for_json(None) is None

    def test_string_passes_through(self):
        assert _sanitize_for_json("hello") == "hello"

    def test_nan_becomes_string(self):
        assert _sanitize_for_json(float("nan")) == "nan"

    def test_pos_inf_becomes_string(self):
        assert _sanitize_for_json(float("inf")) == "inf"

    def test_neg_inf_becomes_string(self):
        assert _sanitize_for_json(float("-inf")) == "-inf"

    def test_actual_null_distinct_from_nan(self):
        # NaN and NULL must remain distinguishable after sanitization
        assert _sanitize_for_json(float("nan")) != _sanitize_for_json(None)

    def test_round_trip_via_float(self):
        # The whole point of stringifying is preservation: float() must
        # reconstruct the exact same special value.
        assert math.isnan(float(_sanitize_for_json(float("nan"))))
        assert float(_sanitize_for_json(float("inf"))) == float("inf")
        assert float(_sanitize_for_json(float("-inf"))) == float("-inf")

    def test_dict_recursion(self):
        out = _sanitize_for_json({"a": float("nan"), "b": 1, "c": None})
        assert out == {"a": "nan", "b": 1, "c": None}

    def test_list_recursion(self):
        out = _sanitize_for_json([1, float("inf"), "x", float("nan")])
        assert out == [1, "inf", "x", "nan"]

    def test_tuple_becomes_list(self):
        # Tuples don't survive JSON anyway; normalize to list during sanitization.
        out = _sanitize_for_json((1, float("nan")))
        assert out == [1, "nan"]

    def test_nested_recursion(self):
        out = _sanitize_for_json({"rows": [{"v": float("nan")}, {"v": 2.0}]})
        assert out == {"rows": [{"v": "nan"}, {"v": 2.0}]}


class TestDumpJson:
    def test_emits_strict_json_for_nan(self):
        # Standard json.loads (no extensions) must accept the output.
        out = _dump_json({"v": float("nan")})
        parsed = json.loads(out)
        assert parsed == {"v": "nan"}

    def test_emits_strict_json_for_inf(self):
        out = _dump_json({"a": float("inf"), "b": float("-inf")})
        parsed = json.loads(out)
        assert parsed == {"a": "inf", "b": "-inf"}

    def test_default_str_fallback(self):
        # Custom non-JSON types fall through ``default=str`` (e.g. Decimal,
        # date) so the dump never crashes on a stray exotic object.
        from decimal import Decimal
        out = _dump_json({"x": Decimal("1.5")})
        assert json.loads(out) == {"x": "1.5"}

    def test_normal_data_unchanged(self):
        data = {"results": [{"id": 1, "name": "a"}], "total": 1}
        assert json.loads(_dump_json(data)) == data


class TestFormatNumericNonFinite:
    """Regression: _format_numeric used to crash with ValueError on NaN
    because it called int(NaN). Fix returns the string form instead."""

    def test_nan_returns_string(self):
        assert _format_numeric(float("nan")) == "nan"

    def test_pos_inf_returns_string(self):
        assert _format_numeric(float("inf")) == "inf"

    def test_neg_inf_returns_string(self):
        assert _format_numeric(float("-inf")) == "-inf"

    def test_nan_with_decimals_flag(self):
        # The decimals/currency branches also went through int() — make
        # sure they don't blow up either.
        assert _format_numeric(float("nan"), decimals=True) == "nan"

    def test_nan_with_currency_flag(self):
        assert _format_numeric(float("nan"), currency=True) == "nan"

    def test_finite_integer_unchanged(self):
        assert _format_numeric(42) == "42"

    def test_finite_float_unchanged(self):
        assert _format_numeric(3.14) == "3.14"

    def test_none_unchanged(self):
        assert _format_numeric(None) == ""

    def test_empty_string_unchanged(self):
        assert _format_numeric("") == ""


class TestCsvCell:
    def test_none_becomes_empty(self):
        assert _csv_cell(None) == ""

    def test_string_passes_through(self):
        assert _csv_cell("hello") == "hello"

    def test_int_passes_through(self):
        assert _csv_cell(42) == 42

    def test_list_serialized_as_json(self):
        # Regression: lists used to emit Python repr (`[1, 2, 3]` with spaces),
        # which is *almost* JSON but breaks once strings or bools enter.
        out = _csv_cell([1, 2, 3])
        assert json.loads(out) == [1, 2, 3]

    def test_dict_serialized_as_json(self):
        # Regression: dicts emitted Python repr (`{'k': 1}` with single quotes),
        # which is not valid JSON. Now uses double quotes.
        out = _csv_cell({"k": 1, "n": 42})
        parsed = json.loads(out)
        assert parsed == {"k": 1, "n": 42}

    def test_nested_list_serialized(self):
        out = _csv_cell([[1, 2], [3, 4]])
        assert json.loads(out) == [[1, 2], [3, 4]]

    def test_dict_with_nan_uses_string_form(self):
        # Sanitization composes: a dict containing NaN must emit valid JSON.
        out = _csv_cell({"v": float("nan")})
        assert json.loads(out) == {"v": "nan"}


class TestOutputCsvIntegration:
    def _capture(self, results, columns):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _output_csv(results, columns)
        return buf.getvalue()

    def test_array_cell_round_trips_via_dictreader(self):
        out = self._capture([{"arr": [1, 2, 3]}], ["arr"])
        rows = list(csv.DictReader(io.StringIO(out)))
        assert json.loads(rows[0]["arr"]) == [1, 2, 3]

    def test_jsonb_cell_round_trips_via_dictreader(self):
        out = self._capture([{"j": {"k": "v", "n": 42}}], ["j"])
        rows = list(csv.DictReader(io.StringIO(out)))
        assert json.loads(rows[0]["j"]) == {"k": "v", "n": 42}

    def test_null_renders_as_empty(self):
        out = self._capture([{"x": None}], ["x"])
        rows = list(csv.DictReader(io.StringIO(out)))
        assert rows[0]["x"] == ""

    def test_header_emitted(self):
        out = self._capture([{"a": 1, "b": 2}], ["a", "b"])
        assert out.splitlines()[0] == "a,b"


class TestOutputMarkdownNoCrashOnNaN:
    """Regression: ``--md`` used to crash with
    ``cannot convert float NaN to integer`` because the numeric path
    called ``int(NaN)``."""

    def _capture(self, results, columns):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _output_markdown(results, columns)
        return buf.getvalue()

    def test_nan_renders_without_crash(self):
        # If the bug regresses, this raises ValueError before returning.
        out = self._capture([{"n": float("nan")}], ["n"])
        # Must include the header and a row containing "nan"
        assert "| n |" in out
        assert "nan" in out

    def test_inf_renders_without_crash(self):
        out = self._capture([{"n": float("inf")}], ["n"])
        assert "inf" in out

    def test_finite_numeric_still_formatted(self):
        out = self._capture([{"x": 1234}], ["x"])
        # Numeric column gets thousands-separator formatting
        assert "1,234" in out


class TestQuotaNotice:
    """`_print_quota_notice` surfaces a stderr banner when the server
    signals an expensive-column quota refusal or truncation."""

    def test_no_quota_signal_no_banner(self, capsys):
        from tl_cli.output.formatter import _print_quota_notice
        _print_quota_notice({"results": [], "usage": {}})
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_quota_exhausted_emits_banner_with_both_caps(self, capsys):
        from tl_cli.output.formatter import _print_quota_notice
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_retry_after_hours": 24,
            "_billing_quota": {
                "queries_used": 10, "queries_max": 10, "queries_remaining": 0,
                "rows_used": 250, "rows_max": 500, "rows_remaining": 250,
                "window_hours": 24,
            },
        })
        err = capsys.readouterr().err
        assert "Billing quota reached" in err
        # Older-server fallback uses the flat window ("within 24h").
        assert "within 24h" in err
        assert "10/10" in err
        assert "250/500" in err

    def test_quota_precise_retry_at_renders_hours_and_minutes(self, capsys):
        from datetime import datetime, timedelta, timezone
        from tl_cli.output.formatter import _print_quota_notice
        retry_at = datetime.now(timezone.utc) + timedelta(hours=1, minutes=23, seconds=15)
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_retry_after_hours": 24,
            "_billing_earliest_retry_at": retry_at.isoformat(),
            "_billing_quota": {
                "queries_used": 10, "queries_max": 10,
                "rows_used": 250, "rows_max": 500,
                "window_hours": 24,
            },
        })
        err = capsys.readouterr().err
        # Precise ETA wins over the flat fallback.
        assert "1h 23m" in err
        assert "within 24h" not in err

    def test_quota_precise_retry_at_renders_minutes(self, capsys):
        from datetime import datetime, timedelta, timezone
        from tl_cli.output.formatter import _print_quota_notice
        retry_at = datetime.now(timezone.utc) + timedelta(minutes=12, seconds=5)
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_earliest_retry_at": retry_at.isoformat(),
            "_billing_quota": {
                "queries_used": 1, "queries_max": 1,
                "rows_used": 5, "rows_max": 100,
                "window_hours": 1,
            },
        })
        err = capsys.readouterr().err
        assert "12m" in err

    def test_quota_precise_retry_at_renders_seconds(self, capsys):
        from datetime import datetime, timedelta, timezone
        from tl_cli.output.formatter import _print_quota_notice
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=45)
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_earliest_retry_at": retry_at.isoformat(),
            "_billing_quota": {
                "queries_used": 1, "queries_max": 1,
                "rows_used": 5, "rows_max": 100,
                "window_hours": 1,
            },
        })
        err = capsys.readouterr().err
        # Allow a couple of seconds of jitter in formatted output.
        assert ("4" in err and "s" in err) or ("3" in err and "s" in err)
        assert "try again in" in err

    def test_quota_precise_retry_at_in_past_says_now(self, capsys):
        from datetime import datetime, timedelta, timezone
        from tl_cli.output.formatter import _print_quota_notice
        retry_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_earliest_retry_at": retry_at.isoformat(),
            "_billing_quota": {
                "queries_used": 1, "queries_max": 1,
                "rows_used": 5, "rows_max": 100,
                "window_hours": 1,
            },
        })
        err = capsys.readouterr().err
        assert "try again now" in err

    def test_quota_no_retry_field_no_wait_clause(self, capsys):
        from tl_cli.output.formatter import _print_quota_notice
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_quota": {
                "queries_used": 1, "queries_max": 1,
                "rows_used": 5, "rows_max": 100,
                "window_hours": 1,
            },
        })
        err = capsys.readouterr().err
        assert "Billing quota reached" in err
        assert "try again" not in err

    def test_quota_omits_rows_line_when_no_row_cap(self, capsys):
        from tl_cli.output.formatter import _print_quota_notice
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_retry_after_hours": 12,
            "_billing_quota": {
                "queries_used": 5, "queries_max": 5,
                "rows_used": 50, "rows_max": None,
                "window_hours": 12,
            },
        })
        err = capsys.readouterr().err
        assert "expensive queries: 5/5" in err
        assert "expensive rows" not in err

    def test_quota_omits_queries_line_when_no_query_cap(self, capsys):
        from tl_cli.output.formatter import _print_quota_notice
        _print_quota_notice({
            "_billing_quota_exhausted": True,
            "_billing_retry_after_hours": 6,
            "_billing_quota": {
                "queries_used": 0, "queries_max": None,
                "rows_used": 500, "rows_max": 500,
                "window_hours": 6,
            },
        })
        err = capsys.readouterr().err
        assert "expensive rows:    500/500" in err
        assert "expensive queries" not in err


class TestPgPricingEstimate:
    """`output_pricing_estimate` renders the --pricing dry-run result."""

    _SAMPLE = {
        "pricing_estimate": {
            "base": 1.4,
            "multiplier": 4.4,
            "per_row_extra": 280.0,
            "expensive_tables": {"thoughtleaders_channel": 3.0},
            "expensive_columns": {
                "thoughtleaders_channel.outreach_email": 80.0,
                "thoughtleaders_channel.demographic_male_share": 50.0,
            },
            "limit": 100,
            "planner_estimated_rows": 1299016,
            "estimated_cost_at_limit": 28140.26,
        },
        "results": [],
        "usage": {"credits_charged": 1, "balance_remaining": 99},
    }

    def test_table_mode_renders_headline_and_breakdown(self, capsys):
        from tl_cli.output.formatter import output_pricing_estimate
        output_pricing_estimate(self._SAMPLE, "table")
        out = capsys.readouterr().out
        assert "Query cost estimate" in out
        assert "28,140.26" in out
        assert "100 row(s)" in out
        assert "4.4" in out          # multiplier
        assert "280" in out          # per-row extra
        assert "thoughtleaders_channel.outreach_email" in out
        assert "80/row" in out
        assert "table (multiplier)" in out

    def test_json_mode_dumps_full_envelope(self, capsys):
        import json
        from tl_cli.output.formatter import output_pricing_estimate
        output_pricing_estimate(self._SAMPLE, "json")
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["pricing_estimate"]["multiplier"] == 4.4
        assert parsed["pricing_estimate"]["estimated_cost_at_limit"] == 28140.26
        # The estimate keys survive a JSON round-trip for piping into jq.
        assert parsed["pricing_estimate"]["per_row_extra"] == 280.0

    def test_json_mode_credits_footer_on_stderr_not_stdout(self, capsys):
        import json
        from tl_cli.output.formatter import output_pricing_estimate
        output_pricing_estimate(self._SAMPLE, "json")
        captured = capsys.readouterr()
        # stdout must be pure JSON (no usage banner) so `| jq` works.
        json.loads(captured.out)
        assert "credits" in captured.err

    def test_empty_expensive_items_still_renders_headline(self, capsys):
        from tl_cli.output.formatter import output_pricing_estimate
        data = {
            "pricing_estimate": {
                "base": 1.4, "multiplier": 1.4, "per_row_extra": 0.0,
                "expensive_tables": {}, "expensive_columns": {},
                "limit": 10, "planner_estimated_rows": 3,
                "estimated_cost_at_limit": 3.8,
            },
            "results": [], "usage": {"credits_charged": 1},
        }
        output_pricing_estimate(data, "table")
        out = capsys.readouterr().out
        assert "Query cost estimate" in out
        assert "3.8" in out

    def test_flat_backend_no_limit_says_depends_on_rows(self, capsys):
        # Firebolt query with no LIMIT → unbounded → no cost figure.
        from tl_cli.output.formatter import output_pricing_estimate
        data = {
            "pricing_estimate": {
                "base": 1.4, "multiplier": 1.4, "per_row_extra": 0.0,
                "expensive_tables": {}, "expensive_columns": {},
                "limit": None, "planner_estimated_rows": None,
                "estimated_cost_at_limit": None,
            },
            "results": [], "usage": {"credits_charged": 1},
        }
        output_pricing_estimate(data, "table")
        out = capsys.readouterr().out
        assert "Query cost estimate" in out
        assert "depends on rows returned" in out
