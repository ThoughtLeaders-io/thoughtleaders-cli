"""Read-only: `tl schema {pg,fb,es}` returns the live schema reference."""

import pytest


@pytest.mark.parametrize("db", ["pg", "fb", "es"])
def test_schema_returns_named_markdown(tl_json, db):
    data = tl_json("schema", db)
    assert data.get("name") == db, data
    content = data.get("content")
    assert isinstance(content, str) and content.strip(), f"schema {db} returned empty content"
