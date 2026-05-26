"""Tests for `tl describe` output helpers."""

from tl_cli.commands.describe import _print_pg_expensive_section


# Sample shape that the server actually emits under `credits.pg_expensive`:
# three sections (base / tables / columns), each a flat dict of leaves.
_LIVE_PG_EXPENSIVE = {
    "base": {"pg": 1.4},
    "tables": {"thoughtleaders_channel": 3.0},
    "columns": {
        "thoughtleaders_channel.outreach_email": 80.0,
        "thoughtleaders_channel.demographic_male_share": 50.0,
        "thoughtleaders_channel.demographic_usa_share": 50.0,
        "thoughtleaders_channel.demographic_device_primary": 50.0,
        "thoughtleaders_channel.demographic_age_median_value": 50.0,
    },
}


class TestPrintPgExpensiveSection:
    def test_missing_block_renders_nothing(self, capsys):
        _print_pg_expensive_section(None)
        assert capsys.readouterr().out == ""

    def test_empty_dict_renders_nothing(self, capsys):
        _print_pg_expensive_section({})
        assert capsys.readouterr().out == ""

    def test_nested_block_flattens_to_dotted_paths(self, capsys):
        _print_pg_expensive_section(_LIVE_PG_EXPENSIVE)
        out = capsys.readouterr().out
        # Section headers prefix every leaf key.
        assert "base.pg" in out
        assert "tables.thoughtleaders_channel" in out
        assert "columns.thoughtleaders_channel.outreach_email" in out
        assert "columns.thoughtleaders_channel.demographic_male_share" in out
        # The numeric values pass through `_fmt_credits` (integer-valued
        # floats lose the trailing ".0").
        assert "80" in out
        assert "50" in out
        assert "3" in out
        # Title appears.
        assert "PG expensive items (live)" in out

    def test_sections_sort_into_dotted_order(self, capsys):
        """Entries sort lexicographically by their flattened dotted path,
        so `base.*` rows precede `columns.*`, which precede `tables.*`."""
        _print_pg_expensive_section(_LIVE_PG_EXPENSIVE)
        out = capsys.readouterr().out
        base_pos = out.index("base.pg")
        cols_pos = out.index("columns.thoughtleaders_channel.outreach_email")
        tables_pos = out.index("tables.thoughtleaders_channel")
        assert base_pos < cols_pos < tables_pos

    def test_unexpected_leaf_type_surfaces_under_section_name(self, capsys):
        """Forward-compat: if a future server adds a non-dict section
        we render it as-is rather than dropping it silently."""
        _print_pg_expensive_section({"scalar_section": 42, "tables": {"t": 1.0}})
        out = capsys.readouterr().out
        assert "scalar_section" in out
        assert "tables.t" in out
