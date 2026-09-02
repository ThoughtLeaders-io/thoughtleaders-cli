"""The creator-brief scripts: local verification, deterministic HTML, and the
legacy classifier's mechanical guarantees (contract validation, resume keying,
loud no-key exit). The live retrieval and extraction flow has its own files —
``test_fetch_cues.py`` and ``test_assemble_extracts.py``. No network anywhere:
classify_gems' API surface is exercised only up to the point it would need a
key.
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
# build_html.py — the ledger view and the connections page, from facts + meta
# --------------------------------------------------------------------------- #
_META = {"schema": "tl-creator-meta/v1", "channel_id": 42, "channel_name": "Patterrz",
         "generated_at": "2026-08-31", "corpus_window": ["2019-04-02", "2026-08-20"],
         "coverage": {"videos_with_transcript": 412, "videos_matched": 287,
                      "passages": 2252, "windows_judged": 500, "gems": 310, "facts": 6},
         "format": "solo", "latest_video_date": "2026-08-29", "rounds": 2}

_FACTS = [
    {"fact_id": "f1", "claim": "has a dog", "domain": "pets", "confidence": "confirmed",
     "sensitivity": "none", "sensitive": False, "recurrence": 4, "selected": True,
     "quote": "we finally adopted luna from the shelter last spring and she",
     "url": "https://www.youtube.com/watch?v=abc&t=12s"},
    {"fact_id": "f2", "claim": "wears glasses", "domain": "health", "confidence": "confirmed",
     "sensitivity": "lifestyle", "sensitive": False, "recurrence": 2},
    {"fact_id": "f3", "claim": "was diagnosed with ADHD", "domain": "health",
     "confidence": "confirmed", "sensitivity": "clinical", "sensitive": True, "recurrence": 3},
    {"fact_id": "f4", "claim": "daughter is named Maple", "domain": "family",
     "confidence": "confirmed", "sensitivity": "children", "sensitive": True, "recurrence": 5},
    {"fact_id": "f5", "claim": "lives on Elm Street", "domain": "home",
     "confidence": "unconfirmed", "sensitivity": "location", "sensitive": True},
    {"fact_id": "f6", "claim": "lived in LA", "domain": "home", "confidence": "confirmed",
     "sensitivity": "none", "sensitive": False, "superseded_by": "f7",
     "source_url": "https://example.com/about"},
]

_CONN_MD = (
    "---\n"
    "schema: tl-creator-connections/v2\n"
    'channel_name: "Patterrz"\n'
    "brand_name: Acme\n"
    "facts_file: 42-facts.jsonl\n"
    "brand_read_date: 2026-09-02\n"
    "---\n\n"
    "Built from 6 facts.\n\n"
    "## 1. Adopted a rescue dog — **direct**\n\n"
    "> we finally adopted luna [watch](https://youtube.com/w?v=abc&t=12s)\n\n"
    "Acme sells dog food [web]\n\n"
    "## Streams on Sundays — **category precedent**\n\n"
    "Bakes sourdough weekly [social: instagram]\n"
)


def _write_ledger(tmp_path: Path, facts=None, meta=None) -> tuple[Path, Path]:
    facts_path = _write_jsonl(tmp_path / "42-facts.jsonl",
                              _FACTS if facts is None else facts)
    meta_path = tmp_path / "42-meta.json"
    meta_path.write_text(json.dumps(_META if meta is None else meta))
    return facts_path, meta_path


def _render_ledger(tmp_path: Path, facts=None, meta=None) -> str:
    facts_path, meta_path = _write_ledger(tmp_path, facts, meta)
    subprocess.run([sys.executable, str(_SCRIPTS / "build_html.py"),
                    "--facts", str(facts_path), "--meta", str(meta_path)],
                   capture_output=True, text=True, check=True)
    return (tmp_path / "42-profile-ledger.html").read_text()


def _render_conn(tmp_path: Path, md: str, facts=None, meta=None,
                 with_ledger: bool = True) -> str:
    src = tmp_path / "42-7-connections.md"
    src.write_text(md)
    cmd = [sys.executable, str(_SCRIPTS / "build_html.py"), "--in", str(src)]
    if with_ledger:
        facts_path, meta_path = _write_ledger(tmp_path, facts, meta)
        cmd += ["--facts", str(facts_path), "--meta", str(meta_path)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return (tmp_path / "42-7-connections.html").read_text()


def test_ledger_view_renders_meta_tiers_and_citations(tmp_path):
    html = _render_ledger(tmp_path)
    assert "<title>Patterrz — ledger</title>" in html
    assert "built 2026-08-31" in html
    assert "corpus 2019-04-02 → 2026-08-20" in html
    assert "287/412 transcript videos matched" in html
    assert "500 passages judged" in html and "format: solo" in html and "2 rounds" in html
    # every fact, its tier as a badge, and the tier tallies
    assert "6 facts: 5 confirmed, 1 unconfirmed" in html
    # f3 is clinical but discussed in 3 videos, so it is usable in angles and
    # not counted as withheld; children + location are
    assert "1 lifestyle, 1 clinical, 1 children, 1 location — 2 withheld from angles" in html
    assert 'class="badge badge-lifestyle">lifestyle</span>' in html
    assert 'class="badge badge-clinical">clinical</span>' in html
    assert html.count('class="badge badge-withheld"') == 2
    assert "sensitivity: none" in html and "superseded by f7" in html
    assert "daughter is named Maple" in html      # the ledger holds everything
    assert "https://example.com/about" in html
    assert "<script" not in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert ':root[data-theme="dark"]' in html


def test_a_passing_clinical_mention_counts_as_withheld(tmp_path):
    html = _render_ledger(tmp_path, facts=[
        {"claim": "takes medication", "domain": "health", "sensitivity": "clinical",
         "recurrence": 1}])
    assert "1 clinical — 1 withheld from angles" in html


def test_ledger_view_lists_linked_platforms_and_sibling_channels(tmp_path):
    meta = dict(_META, lanes="transcripts",
                context={"social_links": ["https://instagram.com/patterrz", "javascript:x"],
                         "second_channel_candidates": [{"name": "Patterrz Clips", "id": 43}]})
    html = _render_ledger(tmp_path, meta=meta)
    assert "lanes: transcripts" in html
    assert "<h2>Other channels and platforms</h2>" in html
    assert 'href="https://instagram.com/patterrz"' in html
    assert "linked but unread (socials lane not run)" in html
    assert 'href="javascript' not in html and "javascript:x" in html
    assert "Patterrz Clips (id 43) — not mined" in html
    read = _render_ledger(tmp_path, meta=dict(meta, lanes="transcripts+socials"))
    assert "read (socials lane)" in read and "unread" not in read


def test_old_boolean_ledgers_render_as_withheld(tmp_path):
    html = _render_ledger(tmp_path, facts=[
        {"claim": "born 1998", "domain": "family", "sensitive": True},
        {"claim": "has a cat", "domain": "pets", "sensitive": False}])
    assert "1 withheld (untiered)" in html
    assert 'badge-withheld">withheld</span>' in html


def test_connections_page_leads_with_who_they_are_then_ranked_cards(tmp_path):
    html = _render_conn(tmp_path, _CONN_MD)
    assert "<title>Patterrz × Acme</title>" in html
    who, conn = html.split("<h2>Connections</h2>")
    assert "<h2>Who they are</h2>" in who
    assert "format: solo" in who and "videos 2019-04 → 2026-08" in who
    assert "6 facts in the ledger" in who
    # top facts by domain, with a short quote and its link
    assert "has a dog" in who and "we finally adopted luna" in who
    assert 'href="https://www.youtube.com/watch?v=abc&amp;t=12s">watch</a>' in who
    assert "wears glasses" in who and 'badge-lifestyle' in who
    assert "was diagnosed with ADHD" in who and "badge-clinical" in who
    # withheld tiers and superseded facts never reach the brand-facing section
    assert "Maple" not in who and "Elm Street" not in who and "lived in LA" not in who
    # the cards: numbered by order, type badge, provenance labels kept
    assert '<ol class="conn">' in conn and conn.count("<li><div class=\"body\">") == 2
    assert "<h3>Adopted a rescue dog — " in conn      # the "1." is the card's numeral
    assert 'class="badge badge-direct">direct</span>' in conn
    assert 'class="badge badge-precedent">category precedent</span>' in conn
    assert "[web]" in conn and "social: instagram" in conn
    assert "brand read 2026-09-02" in html and "from 42-facts.jsonl" in html
    # the only external reference is the font stylesheet; no script anywhere
    head = html.split("</head>")[0]
    assert head.count("http") == 1 and "fonts.googleapis.com" in head
    assert "<script" not in html


def test_no_fit_verdict_renders_as_prose_without_cards(tmp_path):
    md = ("---\nchannel_name: Patterrz\nbrand_name: Acme\n---\n\n"
          "**No fit**: nothing in the ledger meets Acme. Searched: 3 category terms.\n")
    html = _render_conn(tmp_path, md)
    assert '<ol class="conn">' not in html
    assert 'class="badge badge-nofit">No fit</span>' in html
    assert "Searched: 3 category terms" in html


def test_connections_page_without_a_ledger_has_no_who_section(tmp_path):
    html = _render_conn(tmp_path, _CONN_MD, with_ledger=False)
    assert "Who they are" not in html and '<ol class="conn">' in html


def test_html_escapes_untrusted_markdown_text(tmp_path):
    html = _render_conn(tmp_path, "# T\n\nquote says <script>alert(1)</script>\n",
                        with_ledger=False)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_link_target_quote_cannot_break_out_of_href(tmp_path):
    html = _render_conn(tmp_path, (
        '# T\n\n[click](https://x.com/a"onmouseover="alert(1))\n'), with_ledger=False)
    assert 'onmouseover="alert' not in html
    assert "&quot;onmouseover=&quot;" in html


def test_markdown_h1_title_is_not_double_escaped(tmp_path):
    html = _render_conn(tmp_path, "# Rhett & Link\n\nhello\n", with_ledger=False)
    assert "<title>Rhett &amp; Link</title>" in html
    assert "&amp;amp;" not in html


def test_href_ampersands_escape_exactly_once(tmp_path):
    html = _render_conn(tmp_path,
                        "[watch](https://www.youtube.com/watch?v=abc&t=90s)\n",
                        with_ledger=False)
    assert 'href="https://www.youtube.com/watch?v=abc&amp;t=90s"' in html
    assert "&amp;amp;" not in html


def test_ledger_links_only_http_schemes(tmp_path):
    facts = [{"fact_id": "f1", "claim": "grew up in Ohio",
              "url": "javascript:alert(1)",
              "source_url": "https://example.com/about"}]
    ledger = _render_ledger(tmp_path, facts=facts)
    assert 'href="javascript' not in ledger
    assert "javascript:alert(1)" in ledger          # still visible as text
    assert 'href="https://example.com/about"' in ledger


def test_who_they_are_link_only_http_schemes(tmp_path):
    facts = [{"fact_id": "f1", "claim": "grew up in Ohio", "domain": "origin",
              "quote": "I grew up in Ohio", "url": "javascript:alert(1)",
              "sensitivity": "none"}]
    html = _render_conn(tmp_path, _CONN_MD, facts=facts)
    who = html.split("<h2>Connections</h2>")[0]
    assert 'href="javascript' not in who and "grew up in Ohio" in who


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


# --------------------------------------------------------------------------- #
# classify_gems.py — the legacy cheap-API path (no longer in the pipeline)
# --------------------------------------------------------------------------- #
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
