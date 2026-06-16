"""Read-only: `tl db fb` runs a leading-index lookup + a --pricing dry-run.

Firebolt requires an equality/IN filter on the table's leading index column
(`channel_id` for `article_metrics`). This mirrors the documented usage —
fetch one video-metric row for a channel. `330053` is a representative channel
that has metrics; the assertion tolerates 0 rows so the test stays robust if
that channel's snapshots change.
"""

# Selective, cheap, read-only lookup on the leading index column.
_FB_QUERY = "SELECT channel_id, id FROM article_metrics WHERE channel_id = 330053 LIMIT 1"


def test_db_fb_indexed_lookup(tl_json):
    data = tl_json("db", "fb", _FB_QUERY)
    results = data.get("results")
    assert isinstance(results, list), data
    assert len(results) <= 1  # LIMIT 1
    assert all({"channel_id", "id"} <= row.keys() for row in results), results
    assert "usage" in data


def test_db_fb_pricing_dry_run(tl_json):
    data = tl_json("db", "fb", _FB_QUERY, "--pricing")
    assert "pricing_estimate" in data, data
