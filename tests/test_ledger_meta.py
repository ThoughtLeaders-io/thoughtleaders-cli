"""ledger_meta.py: the meta record is derived from the build's files, and the
reuse decision follows the freshness rule (≤5 new uploads and ≤60 days
reuses; more of either refreshes; flags override). No network: the one index
count is mocked."""

import datetime as dt
import gzip
import json
import sys
from pathlib import Path

_SCRIPTS = (Path(__file__).resolve().parents[1]
            / "skills" / "tl-creator-brief" / "scripts")
sys.path.insert(0, str(_SCRIPTS))
import ledger_meta  # noqa: E402


def _jsonl(path: Path, rows: list[dict], gz: bool = False) -> Path:
    text = "".join(json.dumps(r) + "\n" for r in rows)
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        path.write_text(text)
    return path


def _build_dir(tmp_path: Path, channel: int = 42) -> tuple[Path, Path]:
    profiles = tmp_path / "tl-creator-profiles"
    corpus = profiles / ".corpus" / str(channel)
    corpus.mkdir(parents=True)
    _jsonl(profiles / f"{channel}-facts.jsonl", [
        {"fact_id": "f1", "claim": "has a dog", "sensitivity": "none"},
        {"fact_id": "f2", "claim": "wears glasses", "sensitivity": "lifestyle"},
        {"fact_id": "f3", "claim": "lives in Austin", "sensitivity": "none"},
    ])
    _jsonl(corpus / "corpus.jsonl.gz", [
        {"id": "42:a", "publication_date": "2019-04-02", "cues": []},
        {"id": "42:b", "publication_date": "2026-08-20", "cues": []},
        {"id": "42:c", "publication_date": None, "cues": []},
    ], gz=True)
    _jsonl(corpus / "windows.jsonl.gz", [{"id": "42:a"}] * 7, gz=True)
    _jsonl(corpus / "windows-r2.jsonl.gz", [{"id": "42:b"}] * 3, gz=True)
    _jsonl(corpus / "classified.jsonl", [{"window": {}}] * 6)
    _jsonl(corpus / "gems.jsonl", [{"window": {}}] * 4)
    (corpus / "fetch.json").write_text(json.dumps(
        {"videos_with_transcript": 120, "latest_video_date": "2026-08-25"}))
    (corpus / "fetch-r2.json").write_text(json.dumps(
        {"videos_with_transcript": 121, "latest_video_date": "2026-08-29"}))
    return profiles, corpus


def test_write_derives_every_count_from_the_files(tmp_path, capsys):
    profiles, corpus = _build_dir(tmp_path)
    rc = ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles),
                           "--channel-name", "Patterrz", "--format", "solo"])
    assert rc == 0
    meta = json.loads((profiles / "42-meta.json").read_text())
    assert meta["schema"] == "tl-creator-meta/v1"
    assert meta["channel_id"] == 42 and meta["channel_name"] == "Patterrz"
    assert meta["corpus_window"] == ["2019-04-02", "2026-08-20"]
    assert meta["coverage"] == {"videos_with_transcript": 121, "videos_matched": 3,
                                "passages": 10, "windows_judged": 6, "gems": 4,
                                "facts": 3}
    assert meta["format"] == "solo"
    assert meta["latest_video_date"] == "2026-08-29"   # newest across rounds
    assert meta["rounds"] == 2                          # one fetch summary per round
    assert meta["facts_file"] == "42-facts.jsonl"
    assert "credits_spent" not in meta and "missing" not in meta
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert printed["meta"].endswith("42-meta.json")


def test_write_falls_back_to_the_corpus_when_no_fetch_summary(tmp_path):
    profiles, corpus = _build_dir(tmp_path)
    (corpus / "fetch.json").unlink(), (corpus / "fetch-r2.json").unlink()
    ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles),
                      "--rounds", "1", "--credits-spent", "1840"])
    meta = json.loads((profiles / "42-meta.json").read_text())
    assert meta["latest_video_date"] == "2026-08-20"    # newest stored video
    assert meta["coverage"]["videos_with_transcript"] == 0
    assert meta["missing"] == ["fetch.json"]
    assert meta["rounds"] == 1 and meta["credits_spent"] == 1840


def test_write_carries_descriptive_fields_over_from_the_existing_record(tmp_path):
    profiles, corpus = _build_dir(tmp_path)
    ctx = tmp_path / "context.json"
    ctx.write_text(json.dumps({"social_links": ["https://x.com/p"], "about_text": "long",
                               "second_channel_candidates": [
                                   {"name": "Clips", "link": "https://youtube.com/@c",
                                    "source": "social_links", "extra": "dropped"}]}))
    ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles),
                      "--channel-name", "Patterrz", "--format", "solo",
                      "--format-evidence", "fp 41/1k", "--credits-spent", "12",
                      "--lanes", "transcripts+socials", "--context", str(ctx)])
    first = json.loads((profiles / "42-meta.json").read_text())
    assert first["lanes"] == "transcripts+socials"
    assert first["context"] == {"social_links": ["https://x.com/p"],
                                "second_channel_candidates": [
                                    {"name": "Clips", "link": "https://youtube.com/@c",
                                     "source": "social_links"}]}
    # a refresh write passes only what changed
    ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles),
                      "--rounds", "3"])
    again = json.loads((profiles / "42-meta.json").read_text())
    for key in ("channel_name", "format", "format_evidence", "credits_spent", "lanes",
                "context"):
        assert again[key] == first[key], key
    assert again["rounds"] == 3
    # and a value passed again wins
    ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles),
                      "--format", "interview"])
    assert json.loads((profiles / "42-meta.json").read_text())["format"] == "interview"


def test_write_defaults_lanes_to_transcripts(tmp_path):
    profiles, _ = _build_dir(tmp_path)
    ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles)])
    assert json.loads((profiles / "42-meta.json").read_text())["lanes"] == "transcripts"


def test_write_refuses_without_a_ledger(tmp_path):
    profiles = tmp_path / "p"
    profiles.mkdir()
    try:
        ledger_meta.main(["write", "--channel", "42", "--profiles-dir", str(profiles)])
    except SystemExit as exc:
        assert "run the build first" in str(exc)
    else:
        raise AssertionError("no ledger must be a loud failure")


# --------------------------------------------------------------------------- #
# check — the reuse decision
# --------------------------------------------------------------------------- #
def _ledger(tmp_path: Path, generated_at: str, latest: str = "2026-08-20") -> Path:
    profiles = tmp_path / "tl-creator-profiles"
    profiles.mkdir(exist_ok=True)
    _jsonl(profiles / "42-facts.jsonl", [{"fact_id": "f1", "claim": "x"}] * 91)
    (profiles / "42-meta.json").write_text(json.dumps({
        "schema": "tl-creator-meta/v1", "channel_id": 42, "channel_name": "Sydney Watson",
        "generated_at": generated_at, "corpus_window": ["2016-03-01", "2026-08-20"],
        "coverage": {"facts": 91}, "latest_video_date": latest, "rounds": 1}))
    return profiles


def _mock_count(monkeypatch, total: int, seen: list | None = None):
    def fake(args, input_text=None, **kw):
        body = json.loads(input_text)
        if seen is not None:
            seen.append(body)
        return {"total": total, "results": []}
    monkeypatch.setattr(ledger_meta.tl_data, "_tl_json", fake)


def _check(monkeypatch, capsys, profiles: Path, *flags: str, total: int = 0,
           today: dt.date | None = None, seen: list | None = None) -> tuple[str, dict]:
    _mock_count(monkeypatch, total, seen if seen is not None else [])
    if today:
        class _D(dt.date):
            @classmethod
            def today(cls):
                return today
        monkeypatch.setattr(ledger_meta.dt, "date", _D)
    rc = ledger_meta.main(["check", "--channel", "42", "--profiles-dir", str(profiles), *flags])
    assert rc == 0
    lines = capsys.readouterr().out.strip().splitlines()
    if len(lines) == 1:
        return "", json.loads(lines[0])
    return lines[0], json.loads(lines[1])


def test_missing_ledger_means_build_and_no_count(tmp_path, monkeypatch, capsys):
    calls: list = []
    _mock_count(monkeypatch, 0, calls)
    profiles = tmp_path / "empty"
    profiles.mkdir()
    line, out = _check(monkeypatch, capsys, profiles)
    assert out["decision"] == "build" and out["next_round"] == 1
    assert line == "" and calls == []


def test_facts_without_meta_is_an_incomplete_ledger(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-09-01")
    (profiles / "42-meta.json").unlink()
    _, out = _check(monkeypatch, capsys, profiles)
    assert out["decision"] == "build" and "incomplete" in out["reason"]


def test_fresh_ledger_is_reused_with_the_announcement_line(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-09-01")
    line, out = _check(monkeypatch, capsys, profiles, total=3, today=dt.date(2026, 9, 2))
    assert line == ("Found a ledger for Sydney Watson built 2026-09-01 over 2016-03 → "
                    "2026-08-20, 91 facts. 3 videos uploaded since.")
    assert out["decision"] == "reuse" and out["new_videos"] == 3 and out["age_days"] == 1
    assert out["next_round"] == 2 and out["fact_count"] == 91


def test_the_count_is_one_range_query_against_latest_video_date(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-09-01", latest="2026-08-20")
    seen: list = []
    _check(monkeypatch, capsys, profiles, seen=seen)
    assert len(seen) == 1
    body = seen[0]
    assert body["size"] == 0 and body["track_total_hits"] is True
    filters = body["query"]["bool"]["filter"]
    assert {"term": {"channel.id": 42}} in filters
    assert {"range": {"publication_date": {"gt": "2026-08-20"}}} in filters


def test_too_many_new_uploads_refreshes(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-09-01")
    _, out = _check(monkeypatch, capsys, profiles, total=6, today=dt.date(2026, 9, 2))
    assert out["decision"] == "refresh" and "6 new uploads" in out["reason"]
    assert out["next_round"] == 2


def test_an_old_ledger_refreshes_even_with_few_uploads(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-06-01")
    _, out = _check(monkeypatch, capsys, profiles, total=2, today=dt.date(2026, 9, 2))
    assert out["decision"] == "refresh" and "days old" in out["reason"]


def test_thresholds_are_flags(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-06-01")
    _, out = _check(monkeypatch, capsys, profiles, "--max-new-videos", "10",
                    "--max-age-days", "365", total=8, today=dt.date(2026, 9, 2))
    assert out["decision"] == "reuse"


def test_rebuild_and_no_refresh_override_the_rule(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-01-01")
    _, out = _check(monkeypatch, capsys, profiles, "--no-refresh", total=40,
                    today=dt.date(2026, 9, 2))
    assert out["decision"] == "reuse" and out["reason"] == "--no-refresh"
    line, out = _check(monkeypatch, capsys, profiles, "--rebuild", total=0,
                       today=dt.date(2026, 9, 2))
    assert out["decision"] == "build" and out["reason"] == "--rebuild"
    assert line.startswith("Found a ledger")       # still announced, then rebuilt


def test_a_transcripts_only_ledger_refreshes_when_socials_are_asked_for(
        tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-09-01")
    _, out = _check(monkeypatch, capsys, profiles, "--lanes", "transcripts+socials",
                    total=0, today=dt.date(2026, 9, 2))
    assert out["decision"] == "refresh" and "socials lane requested" in out["reason"]
    assert out["lanes"] == "transcripts"
    # the reverse reuses: a ledger that also read socials covers a
    # transcripts-only request
    meta_path = profiles / "42-meta.json"
    meta = json.loads(meta_path.read_text())
    meta["lanes"] = "transcripts+socials"
    meta_path.write_text(json.dumps(meta))
    _, out = _check(monkeypatch, capsys, profiles, "--lanes", "transcripts",
                    total=0, today=dt.date(2026, 9, 2))
    assert out["decision"] == "reuse"
    _, out = _check(monkeypatch, capsys, profiles, "--lanes", "transcripts+socials",
                    total=0, today=dt.date(2026, 9, 2))
    assert out["decision"] == "reuse"


def test_a_failed_count_refreshes_rather_than_reusing_blind(tmp_path, monkeypatch, capsys):
    profiles = _ledger(tmp_path, "2026-09-01")

    def boom(args, input_text=None, **kw):
        raise RuntimeError("index unavailable")
    monkeypatch.setattr(ledger_meta.tl_data, "_tl_json", boom)
    rc = ledger_meta.main(["check", "--channel", "42", "--profiles-dir", str(profiles)])
    assert rc == 0
    captured = capsys.readouterr()
    line, payload = captured.out.strip().splitlines()
    assert "uploads since: unknown" in line
    out = json.loads(payload)
    assert out["decision"] == "refresh" and out["new_videos"] is None
    assert "index unavailable" in captured.err
