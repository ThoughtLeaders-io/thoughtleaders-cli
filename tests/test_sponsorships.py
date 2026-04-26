"""Tests for sponsorship result formatting."""

from tl_cli.commands.sponsorships import _format_results


class TestFormatResults:
    def test_rounds_impressions_guarantee(self):
        results = [{"impressions_guarantee": 12345.7}]
        assert _format_results(results)[0]["impressions_guarantee"] == "12345"

    def test_rounds_impressions_guarantee_string(self):
        results = [{"impressions_guarantee": "9876.4"}]
        assert _format_results(results)[0]["impressions_guarantee"] == "9876"

    def test_rounds_impressions_guarantee_int(self):
        results = [{"impressions_guarantee": 5000}]
        assert _format_results(results)[0]["impressions_guarantee"] == "5000"

    def test_missing_impressions_guarantee(self):
        results = [{"price": 100}]
        out = _format_results(results)[0]
        assert "impressions_guarantee" not in out

    def test_none_impressions_guarantee(self):
        results = [{"impressions_guarantee": None}]
        assert _format_results(results)[0]["impressions_guarantee"] is None

    def test_invalid_impressions_guarantee_left_alone(self):
        results = [{"impressions_guarantee": "not-a-number"}]
        assert _format_results(results)[0]["impressions_guarantee"] == "not-a-number"

    def test_rounds_price_and_cost_alongside(self):
        results = [{"price": 1234.5, "cost": 678.9, "impressions_guarantee": 100000.0}]
        out = _format_results(results)[0]
        assert out["price"] == "1234"
        assert out["cost"] == "678"
        assert out["impressions_guarantee"] == "100000"

    def test_send_date_truncated(self):
        results = [{"send_date": "2026-04-26T12:34:56Z"}]
        assert _format_results(results)[0]["send_date"] == "2026-04-26"
