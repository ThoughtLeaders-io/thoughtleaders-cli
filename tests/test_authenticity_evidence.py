"""Complete authenticity evidence must precede a scored report."""
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/tl-channel-authenticity/scripts"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    for path in SCRIPTS.glob("*.py"):
        monkeypatch.delitem(sys.modules, path.stem, raising=False)
    spec = importlib.util.spec_from_file_location("tl_cli", SCRIPTS / "tl_cli.py")
    seam = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "tl_cli", seam)
    spec.loader.exec_module(seam)
    scraper = importlib.import_module("comment_scraper")
    analyzer = importlib.import_module("comment_analyzer")
    yield scraper, analyzer
    for path in SCRIPTS.glob("*.py"):
        sys.modules.pop(path.stem, None)


def test_failed_comment_retrieval_is_not_empty_evidence(modules, monkeypatch):
    scraper, _ = modules
    def fail(*args):
        raise RuntimeError("upstream blocked")
    monkeypatch.setattr(scraper, "_scrape_ytdlp", fail)
    with pytest.raises(scraper.CommentRetrievalError, match="incomplete"):
        scraper.scrape("video")


def test_successful_empty_comments_remain_valid(modules, monkeypatch):
    scraper, analyzer = modules
    monkeypatch.setattr(scraper, "_scrape_ytdlp", lambda *args: [])
    assert scraper.scrape("video") == []
    result = {"metrics": {}, "llm_batch": [], "flags": [], "subscore": 60}
    analyzer.apply_llm(result, [])
    assert result["subscore"] == 60
    assert result["metrics"]["llm_passes"] == 0
    assert result["metrics"]["llm_organic_share"] is None


@pytest.mark.parametrize("passes", [
    [], [[{"i": 0, "label": "organic"}]],
    [[{"i": 0, "label": "organic"}], []],
    [[{"i": 0, "label": "organic"}]] + [[{"i": 1, "label": "organic"}]],
    [[{"i": 0, "label": "organic"}]] + [[{"i": 0, "label": "unknown"}]],
    [[{"i": 0, "label": "organic"}]] + [[{"i": 0, "label": "organic"}] * 2],
])
def test_incomplete_invalid_classifier_evidence_rejected(modules, passes):
    _, analyzer = modules
    result = {"llm_batch": [{"i": 0}], "metrics": {}, "flags": [], "subscore": 100}
    with pytest.raises(ValueError):
        analyzer.apply_llm(result, passes)
    assert result["subscore"] == 100


def test_complete_passes_preserve_majority_score(modules):
    _, analyzer = modules
    passes = [[{"i": 0, "label": "organic"}, {"i": 2, "label": "bot-like"}]] * 2
    result = {"llm_batch": [{"i": 0}, {"i": 2}], "metrics": {}, "flags": [], "subscore": 85}
    analyzer.apply_llm(result, passes)
    assert result["metrics"]["llm_organic_share"] == .5
    assert result["metrics"]["llm_label_breakdown"] == {"organic": 1, "bot-like": 1}
    assert result["subscore"] == 85
    assert result["hard_fail"] is False


def test_missing_ytdlp_is_explicit(modules, monkeypatch):
    scraper, _ = modules
    def missing(name):
        raise ModuleNotFoundError(name)
    monkeypatch.setattr(scraper.importlib, "import_module", missing)
    with pytest.raises(scraper.CommentRetrievalError, match="install yt-dlp"):
        scraper.scrape("video")


@pytest.mark.parametrize("info", [None, {}, {"comments": None}])
def test_missing_comment_payload_is_not_success(modules, monkeypatch, info):
    scraper, _ = modules
    class Collector:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            return info
    monkeypatch.setattr(scraper.importlib, "import_module", lambda name: SimpleNamespace(YoutubeDL=Collector))
    with pytest.raises(scraper.CommentRetrievalError):
        scraper.scrape("video")


def test_no_videos_is_incomplete(modules):
    scraper, analyzer = modules
    with pytest.raises(scraper.CommentRetrievalError, match="no videos"):
        analyzer.collect({}, [], [])


def test_data_seam_preserves_rows_and_es_shape(modules, monkeypatch):
    seam = importlib.import_module("tl_cli")
    calls = []
    def query(engine, body):
        calls.append((engine, body))
        return {"results": [{"views": 12}], "total": 1}
    monkeypatch.setattr(seam.tl_data, "query", query)
    assert seam.db_pg("SELECT views") == [{"views": 12}]
    assert seam.db_es({"size": 1}) == {"hits": {"hits": [{"_source": {"views": 12}}]}}
    assert calls == [("pg", "SELECT views"), ("es", {"size": 1})]


def test_finalize_rejects_unverified_legacy_collection(modules, tmp_path):
    orchestrator = importlib.import_module("analyze_channel")
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="recollect"):
        orchestrator.finalize(str(state), [])


def test_peer_query_failure_cannot_become_fallback_baseline(modules, monkeypatch):
    peer = importlib.import_module("peer_cohort")
    def fail(*args, **kwargs):
        raise peer.tl_cli.DataError("forbidden")
    monkeypatch.setattr(peer.tl_cli, "channels_similar", fail)
    with pytest.raises(peer.tl_cli.DataError, match="forbidden"):
        peer._peer_ids_via_cli(1)


def test_mcp_suspension_is_not_interpreted_as_failed_or_empty_peer_data(modules, monkeypatch):
    peer = importlib.import_module("peer_cohort")
    pending = peer.tl_cli.tl_data.PendingRequest([{"id": "pending"}])
    def suspend(*args, **kwargs):
        raise pending
    monkeypatch.setattr(peer.tl_cli, "channels_similar", suspend)
    with pytest.raises(peer.tl_cli.tl_data.PendingRequest) as raised:
        peer._peer_ids_via_cli(1)
    assert raised.value is pending
