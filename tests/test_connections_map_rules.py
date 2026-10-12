"""tl-brand-creator-connection map rules: moments are checked before the map is
written, concepts are different ways in, and the page reads in the order the
brand needs it. Invented data only."""
import sys
from pathlib import Path
S = Path(__file__).resolve().parents[1] / "skills" / "tl-brand-creator-connection" / "scripts"
sys.path.insert(0, str(S)); sys.path.insert(0, str(Path(__file__).parent))
import build_html as bh, moment_check as mc

_MAP = (
    "---\nschema: tl-creator-connections/v2\nchannel_id: 42\nchannel_name: \"Patterrz\"\n"
    "creator_name: Robin\nbrand_id: 7\nbrand_name: Acme\nbrand_read_date: 2026-09-02\n---\n\n"
    "## Verdict\n\n**Strong fit.** Robin's stunts keep landing him where Acme fits.\n\n"
    "Best-fit products: the drink mix.\n\n"
    "## About Acme\n\nAcme makes a drink mix.\n\n"
    "## Before the stunt · **Secret-stay series** · **adjacent** · **strong**\n\n"
    "> i forgot my water again\n> [Patterrz, 2026-03-01](https://www.youtube.com/watch?v=aaa&t=40s)\n\n"
    "The moment: he forgets water on a stay.\n\n"
    "- [2026-02-01](https://www.youtube.com/watch?v=bbb&t=90s) Hiding in a box: \"so thirsty in here\"\n\n"
    "The concept: Acme in the bag he brings.\n\nDo: keep it his voice.\n\nDon't: script health claims.\n\n"
    "## After the workout · **Workout clips** · **adjacent** · **strong**\n\n"
    "> just finished leg day\n> [Patterrz, 2026-04-01](https://www.youtube.com/watch?v=ccc&t=10s)\n\n"
    "The moment: he trains between stunts.\n\nThe concept: Acme after the session.\n\n"
    "Do: film it for real.\n\nDon't: promise performance.\n\n"
    "## Done this before\n\n- [2023-05-01](https://www.youtube.com/watch?v=ddd) A bottle brand built into a premise.\n\n"
    "## About Patterrz\n\nRobin runs Patterrz as a crew show.\n\n- f1: Forgets water on stays.\n\n"
    "## Creative guardrails\n\nKeep it in the stunt.\n"
)
_FACTS = [
    {"fact_id": "f1", "claim": "forgets water on stays", "quote": "i forgot my water again",
     "url": "https://www.youtube.com/watch?v=aaa&t=40s", "video": "42:aaa", "start": 40,
     "published": "2026-03-01", "last_seen": "2026-03-01", "confidence": "confirmed",
     "sensitivity": "none", "domain": "habits"},
    {"fact_id": "f2", "claim": "trains legs", "quote": "just finished leg day",
     "url": "https://www.youtube.com/watch?v=ccc&t=10s", "video": "42:ccc", "start": 10,
     "published": "2026-04-01", "last_seen": "2026-04-01", "confidence": "confirmed",
     "sensitivity": "none", "domain": "habits"},
]
_PROBE = {"windows": [{"video_id": "bbb", "start": 90, "published": "2026-02-01",
                       "text": "oh man so thirsty in here right now"}], "brand_windows": []}
_MOMENTS = {"usable": [{"video_id": "aaa", "start": 40}, {"video_id": "bbb", "start": 90},
                       {"video_id": "ccc", "start": 10}],
            "rejected": [], "rival_videos": []}


def _check(md=_MAP, moments=_MOMENTS):
    return bh.check_page(md, _FACTS, {}, _PROBE, moments)


# ---- the map's own contract ----
def test_a_complete_map_passes():
    assert _check() == []


def test_two_concepts_on_the_same_route_fail():
    md = _MAP.replace("**Workout clips**", "**Secret-stay series**")
    assert any("same route" in p for p in _check(md))


def test_a_concept_with_no_route_fails():
    md = _MAP.replace(" · **Workout clips**", "")
    assert any("names no route" in p for p in _check(md))


def test_a_link_that_failed_moment_check_fails_with_its_reason():
    moments = {"usable": [m for m in _MOMENTS["usable"] if m["video_id"] != "bbb"],
               "rejected": [{"video_id": "bbb", "start": 90,
                             "reasons": ["rival named within 120 s: 'Fizzco'"]}],
               "rival_videos": []}
    probs = _check(moments=moments)
    assert any("did not pass moment_check" in p and "Fizzco" in p for p in probs)


def test_a_rival_sponsored_upload_is_history_never_evidence():
    # "done this before" may link a past category partner's upload
    moments = dict(_MOMENTS, rival_videos=["ddd"])
    assert not any("rival brand sponsored" in p for p in _check(moments=moments))
    # a concept may not
    moments = dict(_MOMENTS, rival_videos=["ccc"])
    assert any("rival brand sponsored: ccc" in p for p in _check(moments=moments))


def test_a_plan_needs_its_label():
    moments = {"usable": [{"video_id": "aaa", "start": 40,
                           "label": "said March 2026, not yet confirmed"},
                          *_MOMENTS["usable"][1:]], "rejected": [], "rival_videos": []}
    assert any("without its label" in p for p in _check(moments=moments))
    md = _MAP.replace("The moment: he forgets water on a stay.",
                      "The moment: he says he will pack water (said March 2026, not yet confirmed).")
    assert not any("without its label" in p for p in _check(md, moments))


def test_every_and_always_need_a_count():
    md = _MAP.replace("The moment: he forgets water on a stay.",
                      "The moment: he always forgets water on a stay.")
    assert any("without a count" in p for p in _check(md))
    md = _MAP.replace("The moment: he forgets water on a stay.",
                      "The moment: he forgets water on two of his stays, and always jokes about it in 2 of them.")
    assert not any("without a count" in p for p in _check(md))


def test_the_page_never_claims_certainty():
    md = _MAP.replace("Keep it in the stunt.", "Every fact here is 100% verified.")
    assert any("claims certainty" in p for p in _check(md))


# ---- the page ----
def test_the_page_order_and_the_name_headings():
    _title, (page, _frag) = bh.render_connections(_MAP, _FACTS, {})
    order = [page.index(x) for x in ("<h2>Who Robin is</h2>", "<h2>Robin has done this before</h2>",
                                     '<section class="verdict">', "<h2>Creative concepts</h2>",
                                     "<h2>Robin&#x27;s story so far</h2>")]
    assert order == sorted(order)
    assert 'badge badge-route">Secret-stay series</span>' in page
    assert 'class="badge badge-adjacent"' not in page and 'class="badge badge-strong"' not in page


def test_the_verdict_loses_its_label_without_a_stray_tag():
    _title, (page, _frag) = bh.render_connections(_MAP, _FACTS, {})
    thesis = page.split('<div class="thesis">')[1].split("</div>")[0]
    assert thesis.startswith("<p>Robin") and "</strong>" not in thesis.split("Robin")[0]


def test_a_combined_story_line_takes_date_quote_and_link_from_one_fact():
    idx = {"a": {"fact_id": "a", "quote": "old words", "published": "2021-01-01",
                 "url": "https://www.youtube.com/watch?v=old", "confidence": "confirmed"},
           "b": {"fact_id": "b", "quote": "new words", "published": "2025-01-01",
                 "url": "https://www.youtube.com/watch?v=new", "confidence": "confirmed"}}
    item = bh._who_item(["a", "b"], "line", idx)
    assert item["date"] == "2025-01-01" and item["quote"] == "new words"
    assert "v=new" in item["sources"][0]


# ---- moment_check ----
def test_a_rival_hashtag_matches_without_spaces():
    rx = mc.rival_pattern(["Fizz Co"], ["Acme"])
    assert mc.sponsor_rival("#fizzcobrandpartner", rx) == "fizzco"
    assert mc.sponsor_rival("Thank you to Fizz Co for sponsoring", rx)
    assert mc.rival_pattern(["Acme"], ["Acme"]) is None


def test_will_the_name_is_not_a_plan():
    assert not mc.FUTURE.search("calls Will his childhood hero")
    assert mc.FUTURE.search("I will box a streamer at ten million")
    assert mc.FUTURE.search("I'm not stopping until I win")


def _judge(fact_extra=None, cues=None, summary="", today="2026-10-01", rx=None):
    f = {"fact_id": "f9", "claim": "forgets water", "quote": "i forgot my water again",
         "confidence": "confirmed", "sensitivity": "none", "video": "42:aaa", "start": 40,
         "published": "2026-03-01", "last_seen": "2026-03-01"}
    f.update(fact_extra or {})
    c = {"kind": "fact", "fact": f, "fact_id": "f9", "ref": "42:aaa", "video_id": "aaa",
         "start": f["start"], "quote": f["quote"], "claim": f["claim"],
         "superseded_by": f.get("superseded_by"), "ended": f.get("ended"),
         "last_seen": f["last_seen"], "probe": {}, "members": []}
    cues = cues if cues is not None else [(38.0, "oh no"), (40.0, "i forgot my water again")]
    return mc.judge(c, cues, summary, {"title": "Hiding in a store", "published": f["published"]},
                    rx, today, {"f9": f})


def test_a_checked_moment_is_usable_and_recent():
    rec = _judge()
    assert rec["usable"] and rec["recent"]


def test_a_rival_or_an_awkward_act_nearby_blocks_the_moment():
    rx = mc.rival_pattern(["Fizzco"], ["Acme"])
    rec = _judge(cues=[(40.0, "i forgot my water again"), (95.0, "grab a fizzco from the cooler")], rx=rx)
    assert not rec["usable"] and any("rival named" in r for r in rec["reasons"])
    rec = _judge(cues=[(40.0, "i forgot my water again"), (60.0, "then I stole his shampoo")])
    assert not rec["usable"] and any("awkward act" in r for r in rec["reasons"])


def test_a_premise_partner_line_is_carried_not_blocking():
    rec = _judge(summary="Thank you to Big Mart for letting us film in their store!")
    assert rec["usable"] and "letting us film" in rec["premise"]


def test_a_changed_plan_never_leads_and_a_stale_plan_is_dropped():
    rec = _judge({"superseded_by": "f10"})
    assert not rec["usable"]
    rec = _judge({"quote": "i will pack water next time", "claim": "will pack water",
                  "published": "2024-01-01", "last_seen": "2024-01-01"},
                 cues=[(40.0, "i will pack water next time")])
    assert not rec["usable"] and any("stale plan" in r for r in rec["reasons"])


def test_a_recent_plan_carries_its_label():
    rec = _judge({"quote": "i will pack water next time", "claim": "will pack water",
                  "published": "2026-08-01", "last_seen": "2026-08-01"},
                 cues=[(40.0, "i will pack water next time")])
    assert rec["usable"] and rec["label"] == "said August 2026, not yet confirmed"


def test_a_misquoted_moment_is_blocked():
    rec = _judge(cues=[(40.0, "i remembered my water")])
    assert not rec["usable"] and any("word for word" in r for r in rec["reasons"])
