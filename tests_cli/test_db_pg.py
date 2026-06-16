"""Read-only: `tl db pg` runs real SELECTs against core tables + a --pricing dry-run.

`SELECT id FROM <table> LIMIT 1` over the platform's core entities proves the
caller's sandbox role can read each table and the envelope is well-formed.
Assertions tolerate 0 rows so they hold for any role — an advertiser/publisher
sandbox view of a user-scoped table may legitimately return nothing.
"""

import pytest

# The core entities: channels (creators), brands (sponsors), and adlinks
# (sponsorships — the central record the whole platform revolves around).
CORE_TABLES = ["thoughtleaders_channel", "thoughtleaders_brand", "thoughtleaders_adlink"]


@pytest.mark.parametrize("table", CORE_TABLES)
def test_db_pg_select_id_from_core_table(tl_json, table):
    data = tl_json("db", "pg", f"SELECT id FROM {table} LIMIT 1")
    results = data.get("results")
    assert isinstance(results, list), data
    assert len(results) <= 1  # LIMIT 1
    assert data.get("total") == len(results)
    assert all("id" in row for row in results), results
    assert "balance_remaining" in data.get("usage", {})


def test_db_pg_pricing_dry_run(tl_json):
    # --pricing runs EXPLAIN only (flat 1 credit, no query execution).
    data = tl_json("db", "pg", "SELECT id FROM thoughtleaders_channel LIMIT 1", "--pricing")
    assert "pricing_estimate" in data, data
