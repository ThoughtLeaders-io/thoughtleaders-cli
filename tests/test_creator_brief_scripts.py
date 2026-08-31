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
import selftalk_scan  # noqa: E402


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


def _render_ledger(tmp_path: Path, md: str, facts: list[dict]) -> str:
    _render(tmp_path, md, facts)
    return (tmp_path / "doc-ledger.html").read_text()


_PROFILE_MD = (
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
)

_FACTS = [
    {"claim": "has a dog", "domain": "pets", "confidence": "confirmed",
     "sensitive": False, "source_url": "https://example.com/about"},
    {"claim": "born 1998", "domain": "family", "confidence": "unconfirmed",
     "sensitive": True},
]


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
    # the human page carries no methodology, corpus stats or ledger tallies
    assert "videos with transcript" not in html
    assert "generated" not in html
    assert "format:" not in html
    assert "Full ledger" not in html
    # self-contained: no external fetches of any kind
    assert "http" not in html.split("</head>")[0].replace(
        "http-equiv", "")
    assert "<script" not in html
    assert "@media (prefers-color-scheme: dark)" in html


def test_ledger_view_keeps_meta_tallies_and_citations(tmp_path):
    html = _render_ledger(tmp_path, _PROFILE_MD, _FACTS)
    assert "287/412 videos with transcript" in html
    assert "generated 2026-08-31" in html
    assert "format: solo" in html
    assert "Full ledger: 2 facts" in html and "1 sensitive" in html
    assert "https://example.com/about" in html
    assert "has a dog" in html and "born 1998" in html


def test_human_page_strips_source_names_ledger_keeps_them(tmp_path):
    md = (
        "---\n"
        'channel_name: "Patterrz"\n'
        "---\n\n"
        "## Facts\n\n"
        "- grew up in Ohio (source: Famous Birthdays)\n"
        "- has two cats [src: channel about page]\n"
        "- streams on Sundays [social: instagram]\n"
        "- born in 1998 — source: Famous Birthdays\n"
        "- keeps a garden (via: the channel about page)\n"
    )
    html = _render(tmp_path, md, _FACTS)
    assert "Famous Birthdays" not in html
    assert "about page" not in html
    assert "source" not in html.split("</head>")[1]
    # the claims themselves survive, sans annotation
    assert "grew up in Ohio" in html
    assert "<li>has two cats</li>" in html
    assert "<li>born in 1998</li>" in html
    assert "<li>keeps a garden</li>" in html
    # and the ledger view still carries the citations
    assert "https://example.com/about" in _render_ledger(tmp_path, md, _FACTS)


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


def _run_no_key(tmp_path: Path, windows: list[dict]):
    batches = tmp_path / "batches"
    batches.mkdir()
    (batches / "batch-000.json").write_text(json.dumps(windows))
    ctx = tmp_path / "context.json"
    ctx.write_text("{}")
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / "classify_gems.py"),
         "--batches", str(batches), "--context", str(ctx)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"}), batches


def test_no_api_key_emits_the_fallback_marker_and_its_own_exit_code(tmp_path):
    proc, batches = _run_no_key(tmp_path, [{"id": "1:aaa", "start": 5,
                                            "text": "my dad ran a bakery"}])
    # a code of its own: not argparse's usage 2, not the "errors" 1
    assert proc.returncode == classify_gems.EXIT_FALLBACK_REQUIRED == 20
    marker = next(l for l in proc.stderr.splitlines()
                  if l.startswith("FALLBACK_REQUIRED"))
    fields = dict(kv.split("=", 1) for kv in marker.split()[1:])
    assert fields["reason"] == "missing_api_key"
    # the fallback consumes exactly these files, so the path must resolve
    assert Path(fields["batches_dir"]) == batches.resolve()
    assert fields["batch_files"] == "1" and fields["windows"] == "1"
    assert "CREATOR_BRIEF_LLM_API_KEY" in proc.stderr
    assert "fall back" in proc.stderr


def test_no_api_key_still_prints_its_funnel_line(tmp_path):
    proc, _ = _run_no_key(tmp_path, [{"id": "1:aaa", "start": 5, "text": "x"},
                                     {"id": "1:bbb", "start": 9, "text": "y"}])
    line = next(l for l in proc.stderr.splitlines()
                if l.startswith("FUNNEL stage=classify"))
    fields = dict(kv.split("=", 1) for kv in line.split()[1:])
    assert fields["path"] == "fallback_required"
    assert fields["windows_total"] == "2" and fields["gems"] == "0"
    assert float(fields["elapsed_s"]) >= 0


def test_concurrency_comes_from_the_env_within_bounds(monkeypatch):
    monkeypatch.delenv("CREATOR_BRIEF_LLM_CONCURRENCY", raising=False)
    assert classify_gems.env_concurrency() == classify_gems.CONCURRENCY == 16
    monkeypatch.setenv("CREATOR_BRIEF_LLM_CONCURRENCY", "8")
    assert classify_gems.env_concurrency() == 8
    monkeypatch.setenv("CREATOR_BRIEF_LLM_CONCURRENCY", "9999")
    assert classify_gems.env_concurrency() == classify_gems.MAX_CONCURRENCY
    monkeypatch.setenv("CREATOR_BRIEF_LLM_CONCURRENCY", "0")
    assert classify_gems.env_concurrency() == classify_gems.MIN_CONCURRENCY
    monkeypatch.setenv("CREATOR_BRIEF_LLM_CONCURRENCY", "lots")
    assert classify_gems.env_concurrency() == classify_gems.CONCURRENCY


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


def test_full_spec_prompt_embeds_both_rubric_files_and_the_context():
    prompt = classify_gems.build_prompt(
        classify_gems.load_rubric(full_spec=True), {"channel_name": "Patterrz"},
        [{"id": "1:aaa", "start": 5, "text": "my dad ran a bakery"}])
    flat = " ".join(prompt.split())
    assert "single home of the attribution doctrine" in flat  # rules text
    assert "self-disclosure" in prompt                   # spec text
    assert '"channel_name": "Patterrz"' in prompt
    assert "my dad ran a bakery" in prompt
    assert '{"results": [...]}' in prompt


def test_condensed_wire_contract_is_small_and_keeps_the_contract():
    condensed = classify_gems.load_rubric(full_spec=False)
    full = classify_gems.load_rubric(full_spec=True)
    # the payload trim is the point: the docs were resent on every chunk
    assert len(condensed) < 2500 < len(full)
    # ...but every clause the verdicts are validated against survives
    for domain in classify_gems.LIFE_DOMAINS:
        assert domain in condensed
    for speaker in classify_gems.SPEAKERS:
        assert speaker in condensed
    for field in ("self_disclosure", "life_domain", "speaker_guess",
                  "sensitive", "entity_corrections", "notable"):
        assert field in condensed
    assert "in_sponsor_read" in condensed        # voice attribution
    assert "format_hint" in condensed            # per-window beats the label
    assert "untrusted" in classify_gems.build_prompt(condensed, {}, [])


# --------------------------------------------------------------------------- #
# codex-review regression fixes
# --------------------------------------------------------------------------- #
def test_link_target_quote_cannot_break_out_of_href(tmp_path):
    html = _render(tmp_path, (
        '# T\n\n[click](https://x.com/a"onmouseover="alert(1))\n'))
    assert 'onmouseover="alert' not in html
    assert "&quot;onmouseover=&quot;" in html


def test_markdown_h1_title_is_not_double_escaped(tmp_path):
    html = _render(tmp_path, "# Rhett & Link\n\nhello\n")
    assert "<title>Rhett &amp; Link</title>" in html
    assert "&amp;amp;" not in html


def test_locate_prefers_the_occurrence_nearest_the_hint():
    sys.path.insert(0, str(_SCRIPTS))
    from quote_timestamp import locate
    cues = [(10.0, "I grew up in Ohio you know"),
            (200.0, "and then she said I grew up in Ohio too")]
    quote = "I grew up in Ohio"
    assert locate(cues, quote)["start"] == 10
    hit = locate(cues, quote, hint_start=190)
    assert hit["start"] == 200 and hit["occurrences"] == 2


def test_rows_raises_on_withheld_premium_fields():
    shared = _SCRIPTS.parents[1] / "_shared"
    sys.path.insert(0, str(shared))
    import tl_data
    import pytest
    with pytest.raises(tl_data.DataError, match="premium"):
        tl_data._rows({"results": [{"id": 1}],
                       "_upgrade_required": {"message": "upgrade",
                                             "fields": ["transcript"]}})
    assert tl_data._rows({"results": [{"id": 1}]}) == [{"id": 1}]


def test_youtu_be_shortlinks_are_not_second_channel_candidates():
    sys.path.insert(0, str(_SCRIPTS))
    import channel_context
    row = {"external_channel_id": "UCmain", "url": "https://youtube.com/@main"}
    doc = {"social_links": ["https://youtu.be/dQw4w9WgXcQ",
                            "https://youtube.com/@mainVlogs"],
           "description": "watch https://youtu.be/abc123 now"}
    cands = channel_context.second_channel_candidates(row, doc)
    assert [c["link"] for c in cands] == ["https://youtube.com/@mainVlogs"]


def test_href_ampersands_escape_exactly_once(tmp_path):
    html = _render(tmp_path,
                   "[watch](https://www.youtube.com/watch?v=abc&t=90s)\n")
    assert 'href="https://www.youtube.com/watch?v=abc&amp;t=90s"' in html
    assert "&amp;amp;" not in html


# --------------------------------------------------------------------------- #
# selftalk_scan.py — the model-layer budget (stride-sampler regression)
# --------------------------------------------------------------------------- #
def _win(i: int, score: int, lang: str, day: int = 1) -> dict:
    return {"id": f"1:vid{i:04d}", "start": i, "language": lang,
            "rank_score": score, "published": f"2024-01-{day:02d}"}


def _kept(windows: list[dict]) -> list[dict]:
    """The sort main() applies before the cap: (-rank_score, id, start)."""
    return sorted(windows, key=lambda c: (-c["rank_score"], c["id"],
                                          c["start"]))


def test_zero_score_windows_cannot_displace_ranked_ones():
    """The pre-fix sampler split the pool by score SIGN, so a flood of
    zero-score English windows was treated as 'unranked' and stride-sampled
    over the handful of high-scoring ones. Split is by lexical status."""
    gems = [_win(i, 9 - i % 3, "en") for i in range(20)]
    flood = [_win(1000 + i, 0, "en", day=(i % 28) + 1) for i in range(3000)]
    batched = selftalk_scan.select_batched(_kept(gems + flood), 500, "auto")

    assert len(batched) == 500
    ids = {w["id"] for w in batched}
    assert all(g["id"] in ids for g in gems), "top-ranked windows were dropped"
    # everything English is ranked, so the batch is the top 500 by score —
    # a zero-score window only appears after every scored one is in
    scores = [w["rank_score"] for w in batched]
    assert scores == sorted(scores, reverse=True)
    assert scores[:20] == [9, 9, 9, 9, 9, 9, 9, 8, 8, 8, 8, 8, 8, 8,
                           7, 7, 7, 7, 7, 7]


def test_unranked_pool_is_strided_across_history_not_truncated():
    """Non-English windows are never scored, so they are sampled evenly over
    publication order rather than taken from one end of the channel."""
    ranked = [_win(i, 5, "en") for i in range(100)]
    unranked = [_win(1000 + i, 0, "es", day=(i % 28) + 1) for i in range(900)]
    batched = selftalk_scan.select_batched(_kept(ranked + unranked), 200,
                                           "auto")

    assert len(batched) == 200
    kept_ranked = [w for w in batched if w["language"] == "en"]
    kept_unranked = [w for w in batched if w["language"] == "es"]
    # proportional split (100/1000 of 200), and every ranked window survives
    assert len(kept_ranked) == 20 and len(kept_unranked) == 180
    days = {w["published"] for w in kept_unranked}
    assert len(days) >= 20, "the stride collapsed onto one end of history"


def test_cap_is_a_no_op_below_the_ceiling():
    kept = _kept([_win(i, i % 4, "en") for i in range(50)])
    assert selftalk_scan.select_batched(kept, 500, "auto") == kept
    assert selftalk_scan.select_batched(kept, 0, "auto") == kept   # uncapped


def test_lexicon_off_makes_every_window_unranked():
    kept = _kept([_win(i, 5, "en", day=(i % 28) + 1) for i in range(100)])
    assert all(not selftalk_scan.is_lexical(w, "off") for w in kept)
    batched = selftalk_scan.select_batched(kept, 10, "off")
    assert len(batched) == 10
    assert len({w["published"] for w in batched}) >= 8   # strided, not sliced


def test_limit_bounds_the_fallback_batch_set(tmp_path):
    # a --limit spot-check with no key must not hand the fan-out the full
    # batch set: the marker points at a re-batched dir of just N windows
    batches = tmp_path / "batches"
    batches.mkdir()
    for n in (1, 2):
        (batches / f"batch-00{n}.json").write_text(json.dumps(
            [{"id": f"{n}:{i}", "start": i, "text": "my dad ran a bakery"}
             for i in range(3)]))
    ctx = tmp_path / "context.json"
    ctx.write_text("{}")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "classify_gems.py"),
         "--batches", str(batches), "--context", str(ctx),
         "--limit", "2", "--chunk-size", "2"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == classify_gems.EXIT_FALLBACK_REQUIRED
    marker = next(l for l in proc.stderr.splitlines()
                  if l.startswith("FALLBACK_REQUIRED"))
    fields = dict(kv.split("=", 1) for kv in marker.split()[1:])
    limited = Path(fields["batches_dir"])
    assert limited.name == "batches-limit2"
    assert fields["batch_files"] == "1" and fields["windows"] == "2"
    files = sorted(limited.glob("batch-*.json"))
    assert len(files) == 1
    assert len(json.loads(files[0].read_text())) == 2


def test_connect_documents_keep_provenance_labels(tmp_path):
    md = ("---\n"
          "channel_name: Test Channel\n"
          "brand_name: Acme\n"
          "---\n"
          "\n"
          "- Bakes sourdough weekly [social: instagram]\n")
    page = _render(tmp_path, md)
    # connection maps require their provenance labels; only the PROFILE
    # one-pager is source-stripped
    assert "social: instagram" in page


def test_ledger_links_only_http_schemes(tmp_path):
    facts = [{"fact_id": "f1", "claim": "grew up in Ohio",
              "url": "javascript:alert(1)",
              "source_url": "https://example.com/about"}]
    ledger = _render_ledger(tmp_path, _PROFILE_MD, facts)
    assert 'href="javascript' not in ledger
    assert "javascript:alert(1)" in ledger          # still visible as text
    assert 'href="https://example.com/about"' in ledger


def test_via_parenthetical_prose_survives_the_strip(tmp_path):
    md = ("---\nchannel_name: T\n---\n\n"
          "- Traveled across Europe (via train) (source: Famous Birthdays)\n")
    page = _render(tmp_path, md)
    assert "via train" in page
    assert "Famous Birthdays" not in page


def test_full_spec_rerun_invalidates_condensed_verdicts(tmp_path):
    # resume skips by window; verdicts from the OTHER prompt contract must be
    # discarded, or a --full-spec rerun would be a no-op
    out = tmp_path / "classified.jsonl"
    window = {"id": "1:aaa", "start": 5, "text": "my dad ran a bakery"}
    out.write_text(json.dumps({
        "window": window, "error": None, "contract": "condensed",
        "verdict": {"i": 0, "self_disclosure": True,
                    "speaker_guess": "host"}}) + "\n")
    batches = tmp_path / "batches"
    batches.mkdir()
    (batches / "batch-001.json").write_text(json.dumps([window]))
    ctx = tmp_path / "context.json"
    ctx.write_text("{}")
    # a key is set (resume pruning runs on the API path) but the endpoint is
    # unreachable, so the re-classification attempt errors fast
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "classify_gems.py"),
         "--batches", str(batches), "--context", str(ctx),
         "--out", str(out), "--full-spec"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin",
             "CREATOR_BRIEF_LLM_API_KEY": "test-key",
             "CREATOR_BRIEF_LLM_BASE_URL": "http://127.0.0.1:9"})
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    # the condensed verdict was NOT resumed: the window was re-attempted
    # under the full-spec contract (and errored against the dead endpoint)
    assert all(r.get("contract") == "full-spec" for r in rows)
    assert not any(r.get("error") is None and r.get("verdict") for r in rows)
    assert proc.returncode == 1      # ran (and errored), not skipped-as-done
