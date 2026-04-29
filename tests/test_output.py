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
