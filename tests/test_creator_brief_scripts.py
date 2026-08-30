"""The creator-brief slim-rework scripts: local verification, deterministic
HTML, and the classifier's mechanical guarantees (contract validation, resume
keying, loud no-key exit). No network anywhere — classify_gems' API surface
is exercised only up to the point it would need a key.
"""

import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = (Path(__file__).resolve().parents[1]
            / "skills" / "tl-creator-brief" / "scripts")
sys.path.insert(0, str(_SCRIPTS))
import classify_gems  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


# --------------------------------------------------------------------------- #
# verify_quotes.py
# --------------------------------------------------------------------------- #
def _run_verify(tmp_path: Path, candidates: list[dict]) -> tuple:
    corpus = _write_jsonl(tmp_path / "corpus.jsonl", [
        {"id": "1:vid1", "cues": [
            [10, "so before we start"],
            [14, "I grew up in a tiny town in Ohio"],
            [19, "and my dad ran the bakery there"]]},
        {"id": "1:vid2", "cues": []},
    ])
    infile = _write_jsonl(tmp_path / "candidates.jsonl", candidates)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "verify_quotes.py"),
         "--in", str(infile), "--corpus", str(corpus)],
        capture_output=True, text=True)
    out = [json.loads(line) for line in
           (tmp_path / "candidates.jsonl.verified.jsonl")
           .read_text().splitlines()]
    return proc, json.loads(proc.stdout), out


def test_exact_match_publishes_and_owns_the_timestamp(tmp_path):
    proc, summary, rows = _run_verify(tmp_path, [
        {"provenance": "transcript", "video": "1:vid1", "start": 999,
         "quote": "I grew up in a tiny town in Ohio and my dad ran"}])
    assert proc.returncode == 0
    assert summary["exact"] == 1
    v = rows[0]["verify"]
    assert v["match"] == "exact" and v["found"] is True
    # the located timestamp overrides whatever the candidate carried
    assert rows[0]["start"] == 14
    assert rows[0]["url"].endswith("v=vid1&t=14s")


def test_partial_match_never_accepts(tmp_path):
    proc, summary, rows = _run_verify(tmp_path, [
        {"provenance": "transcript", "video": "1:vid1",
         "quote": "I grew up in a tiny town in Texas with my mother"}])
    assert proc.returncode == 1
    assert summary["partial"] == 1
    v = rows[0]["verify"]
    assert v["match"] == "partial" and v["found"] is False
    assert "unmatched_tail" in v and "warning" in v
    assert rows[0].get("start") is None  # nothing promoted


def test_missing_video_and_no_transcript_are_flagged_not_matched(tmp_path):
    proc, summary, rows = _run_verify(tmp_path, [
        {"provenance": "transcript", "video": "1:vid2", "quote": "anything"},
        {"provenance": "transcript", "video": "1:nope", "quote": "anything"}])
    assert proc.returncode == 1
    assert summary["none"] == 2
    assert all(r["verify"]["found"] is False and "error" in r["verify"]
               for r in rows)


def test_social_and_web_facts_pass_through_unverified(tmp_path):
    proc, summary, rows = _run_verify(tmp_path, [
        {"provenance": "social", "claim": "has a dog",
         "source_url": "https://example.com/p"}])
    assert proc.returncode == 0
    assert summary["passed_through_non_transcript"] == 1
    assert rows[0]["verify"]["match"] == "n/a"


# --------------------------------------------------------------------------- #
# build_html.py
# --------------------------------------------------------------------------- #
def _render(tmp_path: Path, md: str, facts: list[dict] | None = None) -> str:
    src = tmp_path / "doc.md"
    src.write_text(md)
    cmd = [sys.executable, str(_SCRIPTS / "build_html.py"),
           "--in", str(src)]
    if facts is not None:
        cmd += ["--facts", str(_write_jsonl(tmp_path / "facts.jsonl", facts))]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return (tmp_path / "doc.html").read_text()


def test_html_is_self_contained_with_badges_quotes_and_meta(tmp_path):
    html = _render(tmp_path, (
        "---\n"
        'schema: tl-creator-profile/v2\n'
        'channel_name: "Patterrz"\n'
        "generated_at: 2026-08-31\n"
        "videos_total: 412\n"
        "videos_with_transcript: 287\n"
        "format: solo\n"
        "---\n\n"
        "## Facts\n\n"
        "- **Confirmed** grew up in Ohio [watch](https://youtube.com/w?t=1)\n"
        "- This one is **direct** and *notable*\n\n"
        "> we finally adopted luna\n"
    ), facts=[
        {"domain": "pets", "confidence": "confirmed", "sensitive": False},
        {"domain": "family", "confidence": "unconfirmed", "sensitive": True},
    ])
    assert "<title>Patterrz</title>" in html
    assert 'class="badge badge-confirmed"' in html
    assert 'class="badge badge-direct"' in html
    assert "<blockquote>" in html
    assert "287/412 videos with transcript" in html
    assert "2 facts" in html and "1 sensitive" in html
    # self-contained: no external fetches of any kind
    assert "http" not in html.split("</head>")[0].replace(
        "http-equiv", "")
    assert "<script" not in html
    assert "@media (prefers-color-scheme: dark)" in html


def test_html_escapes_untrusted_markdown_text(tmp_path):
    html = _render(tmp_path, "# T\n\nquote says <script>alert(1)</script>\n")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --------------------------------------------------------------------------- #
# classify_gems.py — mechanical guarantees, no network
# --------------------------------------------------------------------------- #
def _verdict(i, **kw):
    v = {"i": i, "self_disclosure": False, "life_domain": None,
         "speaker_guess": "host", "sensitive": False,
         "entity_corrections": {}, "notable": None}
    v.update(kw)
    return v


def test_validate_accepts_the_contract_and_reorders_by_index():
    got = classify_gems.validate(
        [_verdict(1), _verdict(0, self_disclosure=True, life_domain="pets")],
        2)
    assert got is not None and got[0]["life_domain"] == "pets"


def test_validate_rejects_gaps_duplicates_and_bad_enums():
    assert classify_gems.validate([_verdict(0)], 2) is None
    assert classify_gems.validate([_verdict(0), _verdict(0)], 2) is None
    assert classify_gems.validate(
        [_verdict(0, self_disclosure=True, life_domain="astrology")], 1) is None
    assert classify_gems.validate(
        [_verdict(0, speaker_guess="someone")], 1) is None
    assert classify_gems.validate({"not": "a list"}, 1) is None


def test_no_api_key_exits_2_and_names_the_fallback(tmp_path):
    batches = tmp_path / "batches"
    batches.mkdir()
    (batches / "batch-000.json").write_text("[]")
    ctx = tmp_path / "context.json"
    ctx.write_text("{}")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "classify_gems.py"),
         "--batches", str(batches), "--context", str(ctx)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 2
    assert "CREATOR_BRIEF_LLM_API_KEY" in proc.stderr
    assert "fall back" in proc.stderr


def test_resume_skips_clean_verdicts_and_retries_errored_lines(tmp_path):
    out = tmp_path / "classified.jsonl"
    w_done = {"id": "1:aaa", "start": 5, "text": "x"}
    w_err = {"id": "1:bbb", "start": 9, "text": "y"}
    _write_jsonl(out, [
        {"window": w_done, "verdict": _verdict(0), "error": None},
        {"window": w_err, "verdict": None, "error": "json_parse_failed"},
    ])
    done = set()
    kept = []
    for line in out.read_text().splitlines():
        row = json.loads(line)
        if row.get("error") is None and row.get("verdict") is not None:
            done.add(classify_gems.window_key(row["window"]))
            kept.append(line)
    assert classify_gems.window_key(w_done) in done
    assert classify_gems.window_key(w_err) not in done
    assert len(kept) == 1


def test_prompt_embeds_both_rubric_files_and_the_context():
    refs = _SCRIPTS.parent / "references"
    spec = (refs / "gem-classifier.md").read_text()
    rules = (refs / "evidence-rules.md").read_text()
    prompt = classify_gems.build_prompt(
        spec, rules, {"channel_name": "Patterrz"},
        [{"id": "1:aaa", "start": 5, "text": "my dad ran a bakery"}])
    flat = " ".join(prompt.split())
    assert "single home of the attribution doctrine" in flat  # rules text
    assert "self-disclosure" in prompt                   # spec text
    assert '"channel_name": "Patterrz"' in prompt
    assert "my dad ran a bakery" in prompt
    assert '{"results": [...]}' in prompt
