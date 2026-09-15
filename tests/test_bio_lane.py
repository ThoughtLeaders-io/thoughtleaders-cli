"""bio_lane.py — the creator's own written bio as a first-class source.

Covers the three gates the lane owns: the regex boilerplate filter (what is
dropped, what is deliberately NOT dropped), the one extractor batch it builds
(window schema, atomic segments, socials-bio ownership), the identity-lane
records it mints from the classifier's returns (deterministic excerpt, the
same tier hint transcripts get), and the corroboration terms it derives. Plus
the boundary that matters most: a bio window fed to the transcript assembly is
refused, never minted as a quote at a timestamp that does not exist.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = (Path(__file__).resolve().parents[1]
            / "skills" / "tl-creator-brief" / "scripts")
sys.path.insert(0, str(_SCRIPTS))
import assemble_extracts  # noqa: E402
import bio_lane  # noqa: E402


# --------------------------------------------------------------------------- #
# the boilerplate filter
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("segment,reason", [
    ("Welcome to my channel!", "youtube_default"),
    ("Thanks for watching my videos every week", "youtube_default"),
    ("Business inquiries: hello@example.com", "business_inquiry"),
    ("For sponsorships please contact my manager", "business_inquiry"),
    ("Contact me at the address below", "business_inquiry"),
    ("hello@example.com", "email"),
    ("https://example.com/shop", "url_only"),
    ("#gaming #fortnite #shorts", "hashtags_only"),
    ("@someone @someoneelse", "handles_only"),
    ("Subscribe for more and hit the bell", "cta"),
    ("New videos every Tuesday and Friday", "cta"),
    ("Use code DAVID for 10% off my favourite mattress", "cta"),
    ("Doctor. Author.", "too_short"),
    ("", "empty"),
])
def test_drop_reason_catches_boilerplate(segment, reason):
    assert bio_lane.drop_reason(segment) == reason


@pytest.mark.parametrize("segment", [
    "I'm a doctor turned YouTuber based in London.",
    # kept on purpose: the rubric rejects a third-person brag, not the regex.
    # A filter that drops it is making a judgment, which is not its job.
    "The best gaming channel on YouTube.",
    # kept on purpose: real bios are written as lists without pronouns
    "Doctor, author, dad of two.",
    "Former nurse, now full-time creator since 2019.",
])
def test_drop_reason_keeps_real_bio_text(segment):
    assert bio_lane.drop_reason(segment) is None


def test_no_first_person_is_flagged_not_dropped():
    """Codex's objection 6c: a deterministic filter must not make the
    disclosure call. A pronoun-free line survives, carrying `weak_anchor`."""
    windows, dropped = bio_lane.build_windows(
        [{"kind": "about", "platform": "youtube", "url": "https://x", "seen_date": "2026-09-15",
          "text": "Doctor, author, dad of two.\nI live in Manchester."}], channel=7)
    assert dropped == []
    by_text = {w["text"]: w for w in windows}
    assert by_text["Doctor, author, dad of two."]["weak_anchor"] is True
    assert by_text["I live in Manchester."]["weak_anchor"] is False


def test_strip_boilerplate_reports_every_drop_with_a_reason():
    text = ("I'm a doctor turned YouTuber.\n"
            "Business inquiries: hi@example.com\n"
            "#medicine #study\n"
            "I studied at Cambridge.")
    kept, dropped = bio_lane.strip_boilerplate(text)
    assert [k[1] for k in kept] == ["I'm a doctor turned YouTuber.", "I studied at Cambridge."]
    assert [d["reason"] for d in dropped] == ["business_inquiry", "hashtags_only"]
    assert all(d["text"] for d in dropped)


def test_segments_are_atomic():
    """One window gets at most one gem (the rubric's count contract), so a
    three-fact sentence run must arrive as three windows."""
    segs = [s for _, s in bio_lane.segments(
        "I'm a doctor. I live in London. I have two kids.")]
    assert segs == ["I'm a doctor.", "I live in London.", "I have two kids."]


def test_segment_offsets_point_into_the_source_text():
    text = "Line one here.\nI moved to Berlin in 2018."
    for off, seg in bio_lane.segments(text):
        assert text[off:off + len(seg)] == seg


# --------------------------------------------------------------------------- #
# the batch
# --------------------------------------------------------------------------- #
def test_bio_window_carries_no_video_and_no_timestamp():
    windows, _ = bio_lane.build_windows(
        [{"kind": "about", "platform": "youtube", "url": "https://youtube.com/@x",
          "seen_date": "2026-09-15", "text": "I grew up in Leeds and moved to London."}],
        channel=1125633)
    w = windows[0]
    assert w["video_id"] is None
    assert w["retrieval"] == "bio"
    assert w["format_hint"] == "bio"
    assert w["bio_source"] == {"kind": "about", "platform": "youtube",
                               "url": "https://youtube.com/@x", "seen_date": "2026-09-15"}
    # `start` is a character offset into the bio, never a playback position
    assert w["start"] == 0


def test_socials_bio_needs_the_lane_to_have_confirmed_ownership():
    sources, refused = bio_lane.bio_sources(
        {"about_text": "I'm a potter.", "url": "https://youtube.com/@x"},
        [{"platform": "instagram", "url": "https://instagram.com/a", "text": "Potter in Devon",
          "match_confirmed": True},
         {"platform": "instagram", "url": "https://instagram.com/b", "text": "Someone else",
          "match_confirmed": False}],
        seen_date="2026-09-15")
    assert [s["url"] for s in sources] == ["https://youtube.com/@x", "https://instagram.com/a"]
    assert refused[0]["url"] == "https://instagram.com/b"
    assert "confirm" in refused[0]["reason"]


def test_ai_profile_is_never_a_bio_source():
    sources, _ = bio_lane.bio_sources(
        {"about_text": "", "generated_profile": "This channel covers gaming news.",
         "url": "https://youtube.com/@x"}, None, seen_date="2026-09-15")
    assert sources == []


def _run_batch(tmp_path: Path, *args: str) -> dict:
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "bio_lane.py"), "batch",
                           "--out", str(tmp_path), *args],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_batch_cli_writes_one_batch_and_a_summary(tmp_path):
    ctx = tmp_path / "context-full.json"
    ctx.write_text(json.dumps({
        "channel_id": 42, "url": "https://youtube.com/@x", "language": "en",
        "about_text": ("I'm a doctor turned YouTuber.\n"
                       "Business inquiries: hi@example.com\n"
                       "Subscribe for more!\n"
                       "I live in London with my two dogs.")}))
    summary = _run_batch(tmp_path, "--from", str(ctx))
    assert summary["windows"] == 2
    assert summary["dropped_by_reason"] == {"business_inquiry": 1, "cta": 1}
    batch = json.loads(Path(summary["batch"]).read_text())
    assert [w["text"] for w in batch] == ["I'm a doctor turned YouTuber.",
                                          "I live in London with my two dogs."]
    assert Path(summary["summary_file"]).exists()
    assert summary["batches"] == [summary["batch"]]


def test_batch_cli_with_an_all_boilerplate_bio_writes_no_batch(tmp_path):
    ctx = tmp_path / "context-full.json"
    ctx.write_text(json.dumps({"channel_id": 42, "url": "https://youtube.com/@x",
                               "about_text": "Welcome to my channel!\nSubscribe for more!"}))
    summary = _run_batch(tmp_path, "--from", str(ctx))
    assert summary["windows"] == 0
    assert summary["batch"] is None
    assert summary["dropped"] == 2


# --------------------------------------------------------------------------- #
# the boundary: a bio window is not a transcript window
# --------------------------------------------------------------------------- #
def test_transcript_assembly_refuses_a_bio_batch(tmp_path):
    """Codex's blocker 3: assemble_extracts stamps provenance=transcript and
    mints video/start from the window, so an unguarded bio batch would publish
    `watch?v=None&t=0s` as a quote."""
    batches, returns, out = tmp_path / "b", tmp_path / "r", tmp_path / "o"
    for d in (batches, returns, out):
        d.mkdir()
    windows, _ = bio_lane.build_windows(
        [{"kind": "about", "platform": "youtube", "url": "https://youtube.com/@x",
          "seen_date": "2026-09-15", "text": "I grew up in Leeds."}], channel=7)
    (batches / "batch-000.json").write_text(json.dumps(windows))
    (returns / "batch-000.extract.json").write_text(json.dumps(
        {"batch": "000", "windows": 1, "gems": [
            {"i": 0, "start": 0, "anchor": "I grew up in Leeds.", "life_domain": "origin",
             "speaker_guess": "host", "notable": "", "claim": "grew up in Leeds",
             "quote_span": {"first": "I grew", "last": "in Leeds."}, "confidence": "likely"}],
         "not_gems": []}))
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "assemble_extracts.py"),
                           "--batches", str(batches), "--returns", str(returns),
                           "--out", str(out)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "bio_lane.py facts" in proc.stderr
    assert not (out / "candidates.jsonl").exists()


def test_is_bio_window_also_refuses_a_window_with_no_video_id():
    assert assemble_extracts.is_bio_window({"video_id": None, "start": 12})
    assert assemble_extracts.is_bio_window({"retrieval": "bio", "video_id": "abc"})
    assert not assemble_extracts.is_bio_window(
        {"video_id": "abc", "start": 12, "retrieval": "phrase"})


# --------------------------------------------------------------------------- #
# the identity-lane records
# --------------------------------------------------------------------------- #
def _bio_batch(text="I trained as a doctor before I started this channel."):
    windows, _ = bio_lane.build_windows(
        [{"kind": "about", "platform": "youtube", "url": "https://youtube.com/@x",
          "seen_date": "2026-09-15", "text": text}], channel=7)
    return windows


def _gem(**over):
    gem = {"i": 0, "start": 0, "anchor": "I trained as a doctor",
           "life_domain": "work", "speaker_guess": "host", "notable": "",
           "claim": "trained as a doctor before YouTube",
           "quote_span": {"first": "I trained", "last": "a doctor"},
           "confidence": "likely"}
    gem.update(over)
    return gem


def test_a_bio_gem_becomes_an_identity_lane_record():
    windows = _bio_batch()
    facts, skipped = bio_lane.facts_from_returns(windows, {"gems": [_gem()], "not_gems": []})
    assert skipped == []
    f = facts[0]
    assert f["provenance"] == "bio" and f["ref"] == "b1"
    assert f["claim"] == "trained as a doctor before YouTube"
    assert f["source_url"] == "https://youtube.com/@x" and f["seen_date"] == "2026-09-15"
    assert f["corroborates"] is None            # nothing corroborates itself
    assert not {"quote", "video", "start", "url"} & set(f)


def test_the_excerpt_is_cut_from_the_stored_bio_not_written_by_the_model():
    windows = _bio_batch()
    facts, _ = bio_lane.facts_from_returns(windows, {"gems": [_gem()], "not_gems": []})
    assert facts[0]["source_excerpt"] == "I trained as a doctor"
    assert facts[0]["source_excerpt"] in windows[0]["text"]


def test_a_span_that_is_not_in_the_bio_is_refused():
    windows = _bio_batch()
    facts, skipped = bio_lane.facts_from_returns(
        windows, {"gems": [_gem(quote_span={"first": "I won", "last": "an Oscar"})],
                  "not_gems": []})
    assert facts == []
    assert skipped == [{"i": 0, "reason": "span"}]


def test_a_bio_fact_gets_the_same_tier_hint_a_transcript_fact_gets():
    """The extractor does not tier. A bio fact that reached the ledger untiered
    would default to `none` and publish a diagnosis."""
    windows = _bio_batch("I was diagnosed with ADHD at thirty-one.")
    facts, skipped = bio_lane.facts_from_returns(windows, {"gems": [_gem(
        anchor="I was diagnosed with", life_domain="health",
        claim="was diagnosed with ADHD at thirty-one",
        quote_span={"first": "I was", "last": "with ADHD"})], "not_gems": []})
    assert skipped == []
    assert facts[0]["sensitivity"] == "clinical"
    assert facts[0]["sensitivity_source"] == "heuristic"


def test_an_unresolvable_tier_never_publishes():
    windows = _bio_batch()
    facts, skipped = bio_lane.facts_from_returns(
        windows, {"gems": [_gem(sensitivity="spicy")], "not_gems": []})
    assert facts == []
    assert skipped[0]["reason"] == "sensitivity 'spicy'"


def test_a_bio_quoting_someone_else_is_not_the_creator():
    windows = _bio_batch()
    facts, skipped = bio_lane.facts_from_returns(
        windows, {"gems": [_gem(speaker_guess="guest")], "not_gems": []})
    assert facts == []
    assert skipped[0]["reason"] == "voice guest"


def test_a_verdict_about_another_window_is_refused():
    windows = _bio_batch()
    facts, skipped = bio_lane.facts_from_returns(
        windows, {"gems": [_gem(start=999)], "not_gems": []})
    assert facts == []
    assert skipped[0]["reason"] == "start does not match the window"


def test_facts_cli_writes_the_records(tmp_path):
    windows = _bio_batch()
    batch = tmp_path / "batch-000.json"
    batch.write_text(json.dumps(windows))
    returns = tmp_path / "batch-000.extract.json"
    returns.write_text(json.dumps({"batch": "000", "windows": 1,
                                   "gems": [_gem()], "not_gems": []}))
    out = tmp_path / "bio-facts.json"
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "bio_lane.py"), "facts",
                           "--batch", str(batch), "--returns", str(returns),
                           "--out", str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text())
    assert written["counts"] == {"facts": 1, "skipped": 0, "sensitive": 0}
    assert written["facts"][0]["provenance"] == "bio"
