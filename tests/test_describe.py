"""Tests for `tl describe` output helpers."""

from tl_cli.commands.describe import _print_pg_pricing_section


# Sample shape that the server actually emits under `credits.pg_pricing`:
# three sections (default / tables / columns), each a flat dict of leaves.
_LIVE_PG_PRICING = {
    "default": {"pg": 1.0},
    "tables": {"thoughtleaders_adlink": 0.1, "thoughtleaders_channel": 3.0},
    "columns": {
        "thoughtleaders_channel.outreach_email": 80.0,
        "thoughtleaders_channel.demographic_male_share": 50.0,
        "thoughtleaders_channel.demographic_usa_share": 50.0,
        "thoughtleaders_channel.demographic_device_primary": 50.0,
        "thoughtleaders_channel.demographic_age_median_value": 50.0,
    },
}


class TestPrintPgPricingSection:
    def test_missing_block_renders_nothing(self, capsys):
        _print_pg_pricing_section(None)
        assert capsys.readouterr().out == ""

    def test_empty_dict_renders_nothing(self, capsys):
        _print_pg_pricing_section({})
        assert capsys.readouterr().out == ""

    def test_nested_block_flattens_to_dotted_paths(self, capsys):
        _print_pg_pricing_section(_LIVE_PG_PRICING)
        out = capsys.readouterr().out
        # Section headers prefix every leaf key.
        assert "default.pg" in out
        assert "tables.thoughtleaders_channel" in out
        assert "tables.thoughtleaders_adlink" in out
        assert "columns.thoughtleaders_channel.outreach_email" in out
        assert "columns.thoughtleaders_channel.demographic_male_share" in out
        # The numeric values pass through `_fmt_credits` (integer-valued
        # floats lose the trailing ".0").
        assert "80" in out
        assert "50" in out
        assert "3" in out
        # Title appears.
        assert "PG per-row pricing (live)" in out

    def test_directs_user_to_pricing_flag(self, capsys):
        _print_pg_pricing_section(_LIVE_PG_PRICING)
        out = capsys.readouterr().out
        # The note points at the per-query estimator and clarifies these
        # are rates, not a total.
        assert "--pricing" in out
        assert "tl db pg" in out

    def test_sections_sort_into_dotted_order(self, capsys):
        """Entries sort lexicographically by their flattened dotted path,
        so `columns.*` rows precede `default.*`, which precede `tables.*`."""
        _print_pg_pricing_section(_LIVE_PG_PRICING)
        out = capsys.readouterr().out
        cols_pos = out.index("columns.thoughtleaders_channel.outreach_email")
        default_pos = out.index("default.pg")
        tables_pos = out.index("tables.thoughtleaders_channel")
        assert cols_pos < default_pos < tables_pos

    def test_unexpected_leaf_type_surfaces_under_section_name(self, capsys):
        """Forward-compat: if a future server adds a non-dict section
        we render it as-is rather than dropping it silently."""
        _print_pg_pricing_section({"scalar_section": 42, "tables": {"t": 1.0}})
        out = capsys.readouterr().out
        assert "scalar_section" in out
        assert "tables.t" in out
