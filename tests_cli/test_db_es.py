"""Read-only: `tl db es` fetches one channel document + a --pricing dry-run.

Channel metadata lives on channel docs (filtered by the `doc_type` join field),
so this is the ES analogue of "SELECT id FROM channels LIMIT 1". `_source` is
narrowed to `id` to keep the payload (and the per-field charge) minimal.
"""

# One channel document, projecting just `id`.
_CHANNEL_DOC = '{"size": 1, "query": {"term": {"doc_type": "channel"}}, "_source": ["id"]}'


def test_db_es_fetch_one_channel_doc(tl_json):
    data = tl_json("db", "es", _CHANNEL_DOC)
    results = data.get("results")
    assert isinstance(results, list), data
    assert len(results) <= 1  # size: 1
    assert data.get("total", 0) >= len(results)
    assert "usage" in data


def test_db_es_pricing_dry_run(tl_json):
    data = tl_json("db", "es", _CHANNEL_DOC, "--pricing")
    assert "pricing_estimate" in data, data
