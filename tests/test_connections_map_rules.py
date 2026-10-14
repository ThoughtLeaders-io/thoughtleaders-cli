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
    "## Before the stunt · **Challenge series** · **adjacent** · **strong**\n\n"
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
    md = _MAP.replace("**Workout clips**", "**Challenge series**")
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
    assert 'badge badge-route">Challenge series</span>' in page
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
    assert mc.FUTURE.search("I will run a marathon at ten million")
    assert mc.FUTURE.search("I'm not stopping until I win")


def _judge(fact_extra=None, cues=None, summary="", today="2026-10-01", rx=None, latest=None,
           rivals=None):
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
                    rx, today, {"f9": f}, latest, rivals or [], ["Acme"])


def test_a_checked_moment_is_usable_and_recent():
    rec = _judge()
    assert rec["usable"] and rec["recent"]


def test_a_rival_or_an_awkward_act_nearby_blocks_the_moment():
    rec = _judge(cues=[(40.0, "i forgot my water again"), (95.0, "grab a fizzco from the cooler")],
                 rivals=["Fizzco"])
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


def test_a_habit_not_said_for_six_months_has_lapsed():
    fact = {"quote": "every time I hit a million I run a marathon", "claim": "runs a marathon every million",
            "published": "2025-08-01", "last_seen": "2026-01-10"}
    cues = [(40.0, "every time I hit a million I run a marathon")]
    rec = _judge(fact, cues=cues, latest="2026-09-30")
    assert not rec["usable"] and any("lapsed" in r for r in rec["reasons"])
    rec = _judge(fact, cues=cues, latest="2026-03-01")
    assert rec["usable"]


def test_a_rival_that_is_also_a_word_counts_only_as_a_name():
    assert mc.near_rival("what a zinger that was", ["Zing"], ["Acme"]) is None
    assert mc.near_rival("That was a spark of genius", ["Spark"], ["Acme"]) is None
    assert mc.near_rival("Grab a Spark from the fridge", ["Spark"], ["Acme"]) == "Spark"
    assert mc.near_rival("all I have in here is a cold spark and crackers", ["Spark"], ["Acme"])
    # rivals are said by their short name
    assert mc.near_rival("all I have in here is a cold spark and crackers", ["Spark Hydration"], ["Acme"])
    assert mc.near_rival("grabbed a volto stick", ["Drink Volto"], ["Acme"])
    assert mc.near_rival("grab a fizz co please", ["Fizz Co"], ["Acme"]) == "fizz co"


def test_members_are_checked_moments_of_their_fact():
    facts = [{"fact_id": "f1", "video": "42:aaa", "start": 40, "provenance": "transcript",
              "members": ["aaa:40", "bbb:300", "ccc:12"], "claim": "c", "quote": "q"}]
    kinds = [(c["kind"], c["video_id"], c["start"]) for c in mc.candidates(facts, {})]
    assert ("member", "bbb", 300) in kinds and ("member", "ccc", 12) in kinds
    assert ("member", "aaa", 40) not in kinds      # the fact's own moment is the fact


def test_an_audience_count_is_not_money():
    import tier_hint as th
    assert not th.names_money("every 1 million subscribers I have to dye my hair")
    assert not th.names_money("the video hit 2 million views")
    assert th.names_money("I spent 1 million dollars on it")
    assert th.names_money("we won $5,000")


def test_a_link_must_start_where_its_quote_starts():
    m = {"cues": [[100.0, "around the corner I spotted a vending machine"], [112.0, "this is exactly what I needed."]]}
    assert "link &t=112s" in bh._quote_timing(m, "this is exactly what I needed.", 100)
    assert bh._quote_timing(m, "this is exactly what I needed.", 110) is None


def test_a_quote_that_stops_mid_sentence_fails():
    m = {"cues": [[10.0, "it is so cold out here and we have to"], [12.0, "wait like this all night long."]]}
    assert "mid-sentence" in bh._quote_timing(m, "it is so cold out here and we have to", 10)


def test_a_window_holding_a_held_back_ledger_line_is_blocked():
    idx = {"f3": {"fact_id": "f3", "quote": "Sam is also my workout buddy", "confidence": "unconfirmed",
                  "staged_only": True}}
    assert mc.held_back_line("my best friend, Sam is also my workout buddy. But", idx).startswith("f3")


def test_a_moment_inside_an_ad_read_is_blocked():
    rec = mc.judge({"kind": "window", "ref": "42:aaa", "video_id": "aaa", "start": 560,
                    "quote": "i grew up here and we love this team"},
                   [(560.0, "i grew up here and we love this team")], "", {}, None,
                   "2026-10-01", {}, None, [], ["Acme"], [(541.0, 587.0)])
    assert not rec["usable"] and any("ad read" in r for r in rec["reasons"])


def test_a_window_cut_at_other_edges_still_holds_the_held_back_line():
    idx = {"f3": {"fact_id": "f3", "quote": "other than being my best friend, Sam is also my workout buddy.",
                  "confidence": "unconfirmed", "staged_only": True}}
    assert mc.held_back_line("friend, Sam is also my workout buddy. But honestly, he has", idx)
    assert mc.held_back_line("I went to the gym with my buddy today", idx) is None


def test_a_lapsed_span_starts_at_the_first_repeat():
    recs = [{"kind": "fact", "fact_id": "f7", "published": "2025-11-08",
             "said": "said from November 2025 to January 2026"},
            {"kind": "member", "fact_id": "f7", "published": "2025-08-19"}]
    mc.widen_said(recs)
    assert recs[0]["said"] == "said from August 2025 to January 2026"


def test_caption_tags_are_not_words_the_creator_said():
    assert bh._norm_words("we have to [music] stand like this") == "we have to stand like this"


def test_a_clean_sentence_beside_a_held_back_line_stays_usable():
    idx = {"f9": {"fact_id": "f9", "quote": "I'm running a marathon every time I go up a million subscribers",
                  "confidence": "confirmed", "superseded_by": "f10"}}
    rec = mc.judge({"kind": "window", "ref": "42:aaa", "video_id": "aaa", "start": 980,
                    "quote": "we have this entire track to ourselves. Let's get a workout in. "
                             "every time I go up a million subscribers I run another marathon"},
                   [(980.0, "we have this entire track to ourselves. Let's get a workout in."),
                    (984.0, "every time I go up a million subscribers I run another marathon")],
                   "", {}, None, "2026-10-01", idx, None, [], ["Acme"], [])
    assert rec["usable"] and rec["held_back"]["fact_id"] == "f9"
    assert bh._quotes_held_back(rec, "Let's get a workout in.") is None
    assert bh._quotes_held_back(rec, "every time I go up a million subscribers") is not None


def test_a_replaced_phase_stays_in_the_story_as_history():
    old = {"fact_id": "f1", "claim": "runs a marathon every million subscribers", "confidence": "confirmed",
           "sensitivity": "none", "superseded_by": "f2", "quote": "I'm running a marathon", "published": "2025-08-19"}
    held = dict(old, fact_id="f3", confidence="unconfirmed")
    idx = {"f1": old, "f3": held}
    assert bh.story_ok(old, idx)
    assert not bh.story_ok(held, idx)


def test_a_past_phase_in_the_story_must_give_its_span():
    assert bh._HISTORY_SPAN.search("Said from August 2025 to January 2026 that they would run a marathon")
    assert not bh._HISTORY_SPAN.search("Runs a marathon every time the channel gains a million subscribers")


def test_a_secretly_title_marks_the_moment_a_premise():
    assert mc.premise_title("I Secretly Worked At A Pizza Shop")
    assert mc.premise_title("I Tried Every Pizza In Town") is None


def test_setting_off_an_alarm_is_an_awkward_act():
    assert mc.RISKY.search("which is going to set off an alarm")
    assert mc.RISKY.search("we set off the fire alarm")


def test_a_link_counts_from_the_quotes_first_word_inside_a_long_cue():
    m = {"cues": [[399.0, "after walking around all day, I finally found a bench in the park. Oh, wait. Oh,"],
                  [410.4, "tacos. I love tacos."]]}
    assert "link &t=40" in bh._quote_timing(m, "Oh, wait. Oh, tacos. I love tacos.", 399)


def _people_facts():
    rose = {"fact_id": "f1", "claim": "keeps a regular date night with Rose", "confidence": "confirmed",
            "sensitivity": "none", "published": "2025-04-20", "last_seen": "2026-09-20",
            "people": [{"name": "Rose", "relation": "girlfriend"}]}
    fiance = {"fact_id": "f2", "claim": "has a fiance", "confidence": "confirmed", "sensitivity": "none",
              "published": "2026-07-27", "people": []}
    theo = {"fact_id": "f3", "claim": "their cousin Theo", "confidence": "confirmed", "sensitivity": "none",
            "published": "2021-12-27", "people": [{"name": "Theo", "relation": "cousin"}]}
    return [rose, fiance, theo]


def test_a_newer_engagement_makes_the_girlfriend_a_fiancee():
    facts = _people_facts()
    out = bh.people_section(facts, {f["fact_id"]: f for f in facts})
    assert "fiancée" in out and "girlfriend" not in out


def test_a_crew_member_with_the_same_name_does_not_date_the_cousin():
    facts = _people_facts()
    seen = {"theo": [("2025-03-22", "crew"), ("2021-12-27", "family")]}
    out = bh.people_section(facts, {f["fact_id"]: f for f in facts}, seen=seen)
    assert "2025-03" not in out and "2021-12" in out


def test_a_lapsing_relation_carries_its_year_and_kin_do_not():
    room = {"fact_id": "f1", "claim": "as of this video, had a roommate named Quinn", "confidence": "confirmed",
            "sensitivity": "none", "published": "2019-08-08", "people": [{"name": "Quinn", "relation": "roommate"}]}
    kin = {"fact_id": "f2", "claim": "as of this video, their cousin Theo lived out of state",
           "confidence": "confirmed", "sensitivity": "none", "published": "2019-07-31",
           "people": [{"name": "Theo", "relation": "cousin"}]}
    out = bh.people_section([room, kin], {"f1": room, "f2": kin})
    assert "roommate (2019)" in out and "cousin (2019)" not in out


# ---- what the review of the first version caught ----
def test_a_moment_with_no_transcript_is_not_checked_and_not_usable():
    rec = _judge(cues=[])
    assert not rec["usable"] and any("no transcript" in r for r in rec["reasons"])
    rec = mc.judge({"kind": "window", "ref": "42:zzz", "video_id": "zzz", "start": 30,
                    "quote": "i love a cold drink after a run"}, [], "", {}, None, "2026-10-01",
                   {}, None, ["Fizzco"], ["Acme"], [])
    assert not rec["usable"] and any("no transcript" in r for r in rec["reasons"])


def test_a_lane_window_must_be_word_for_word_in_the_captions():
    cues = [(28.0, "so after the run"), (30.0, "i love a cold drink after a run")]
    base = {"kind": "window", "ref": "42:aaa", "video_id": "aaa", "start": 30}
    ok = mc.judge(dict(base, quote="i love a cold drink after a run"), cues, "", {}, None,
                  "2026-10-01", {}, None, [], ["Acme"], [])
    assert ok["usable"]
    bad = mc.judge(dict(base, quote="i love a cold drink after my runs"), cues, "", {}, None,
                   "2026-10-01", {}, None, [], ["Acme"], [])
    assert not bad["usable"] and any("word for word" in r for r in bad["reasons"])


def test_a_read_logged_at_second_zero_is_not_a_span_over_the_opening():
    f = {"fact_id": "f9", "claim": "forgets water", "quote": "i forgot my water again",
         "confidence": "confirmed", "sensitivity": "none", "video": "42:aaa", "start": 2,
         "published": "2026-03-01", "last_seen": "2026-03-01"}
    c = {"kind": "fact", "fact": f, "fact_id": "f9", "ref": "42:aaa", "video_id": "aaa", "start": 2,
         "quote": f["quote"], "claim": f["claim"], "last_seen": f["last_seen"], "probe": {}, "members": []}
    cues = [(0.0, "hey"), (2.0, "i forgot my water again")]
    meta = {"title": "Hiding", "published": "2026-03-01"}
    assert mc.judge(c, cues, "", meta, None, "2026-10-01", {"f9": f}, None, [], ["Acme"],
                    [(-1.0, -1.0)])["usable"]
    assert not mc.judge(c, cues, "", meta, None, "2026-10-01", {"f9": f}, None, [], ["Acme"],
                        [(0.0, 20.0)])["usable"]


def test_idioms_are_neither_plans_nor_habits():
    assert not mc.FUTURE.search("I will never forget my first marathon")
    assert not mc.FUTURE.search("I'll never go back there")
    assert mc.FUTURE.search("I will run it again next year")
    assert not mc.PATTERN.search("I've always loved this city")
    assert not mc.PATTERN.search("I have always wanted to be a pilot")
    assert mc.PATTERN.search("I always forget my water")
    assert mc.PATTERN.search("every time I go up a million subscribers")


def test_a_rival_that_is_also_a_word_sponsors_a_video_only_as_a_name():
    rx = mc.rival_pattern(["Prime", "Monster Energy"], ["Acme"])
    assert mc.sponsor_rival("follow me #vlog its prime time baby", rx) is None
    assert mc.sponsor_rival("my partner and I love monster trucks", rx) is None
    assert mc.sponsor_rival("#primepartner", rx) == "prime"
    assert mc.sponsor_rival("Thanks to Prime for sponsoring", rx) == "Prime"
    assert mc.sponsor_rival("paid partnership with monster energy", rx) == "monster energy"


def test_the_brands_own_past_deals_are_history_not_a_rivals():
    tl = {"category_history": [{"brand": "Acme", "video_id": "own"},
                               {"brand": "Fizzco", "video_id": "theirs"},
                               {"brand": "", "video_id": "unnamed"}]}
    assert mc.history_rival_videos(tl, ["Acme", ""]) == {"theirs", "unnamed"}


def test_a_window_keeps_its_occasion():
    cands = mc.candidates([], {"channel_id": "42", "windows": [
        {"video_id": "bbb", "start": 90, "text": "so thirsty in here", "occasion": "after the workout"}]})
    assert cands[0]["occasion"] == "after the workout" and cands[0]["ref"] == "42:bbb"


def test_a_strength_word_in_a_concept_name_is_not_its_strength():
    md = _MAP.replace("## Before the stunt · **Challenge series** · **adjacent** · **strong**",
                      "## Strong start · **Challenge series** · **adjacent** · **thin**") \
             .replace("## After the workout · **Workout clips** · **adjacent** · **strong**",
                      "## After the workout · **Workout clips** · **adjacent** · **thin**")
    assert any("says 'strong fit' but the concepts make it 'thin fit'" in p for p in _check(md))


def test_the_about_heading_may_carry_the_hosts_name():
    md = _MAP.replace("## About Patterrz", "## About Robin")
    assert not any("missing section" in p for p in _check(md))
    _title, (page, _frag) = bh.render_connections(md, _FACTS, {})
    assert "<h2>Who Robin is</h2>" in page and "Robin runs Patterrz as a crew show" in page


def test_a_story_line_never_names_a_fact_from_a_category_sponsors_upload():
    md = _MAP.replace("- f1: Forgets water on stays.", "- f2: Trains legs between stunts.")
    moments = {"usable": [m for m in _MOMENTS["usable"] if m["video_id"] != "ccc"],
               "rejected": [{"video_id": "ccc", "start": 10, "kind": "fact", "fact_id": "f2",
                             "reasons": ["upload sponsored by a brand in the category history"],
                             "rival_sponsored": True}],
               "rival_videos": ["ccc"]}
    assert any("story line names f2" in p for p in _check(md, moments))


def test_a_count_of_videos_is_not_any_number():
    md = _MAP.replace("The moment: he forgets water on a stay.",
                      "The moment: he always forgets water, as on his 2025 Vegas stay.")
    assert any("without a count" in p for p in _check(md))
    md = _MAP.replace("The moment: he forgets water on a stay.",
                      "The moment: he always forgets water, in 3 videos this year.")
    assert not any("without a count" in p for p in _check(md))


def test_a_curly_apostrophe_still_marks_a_dont_line():
    md = _MAP.replace("Don't: script health claims.", "Don’t: always script health claims.")
    assert not any("without a count" in p for p in _check(md))
    _title, (page, _frag) = bh.render_connections(md, _FACTS, {})
    assert "f-dont" in page


def test_the_captions_own_full_stop_ends_the_quote():
    m = {"cues": [[10.0, "i love this city."], [13.0, "next day we left"]]}
    assert bh._quote_timing(m, "i love this city", 10) is None
    m = {"cues": [[8.0, "the city is big and"], [10.0, "i love this city. next day we left"]]}
    assert bh._quote_timing(m, "i love this city", 10) is None
    m = {"cues": [[8.0, "nothing beats this,"], [10.0, "i am all in. then we left"]]}
    assert bh._quote_timing(m, "i am all in", 10) is None
    m = {"cues": [[10.0, "i love this city and"], [13.0, "its people"]]}
    assert bh._quote_timing(m, "i love this city", 10) == "the quote stops mid-sentence; quote the whole sentence"


def test_a_precedent_cards_lead_quote_is_timed_too():
    md = _MAP.replace(
        "## Done this before",
        "## Thirsty · **Box stunts** · **category precedent** · **thin**\n\n"
        "> oh man so thirsty in here right now\n> [Patterrz, 2026-02-01](https://www.youtube.com/watch?v=bbb&t=72s)\n\n"
        "The moment: he is thirsty in the box.\n\nThe concept: Acme in the box.\n\n"
        "Do: keep it real.\n\nDon't: fake it.\n\n## Done this before")
    moments = {"usable": [*_MOMENTS["usable"][:1], *_MOMENTS["usable"][2:],
                          {"video_id": "bbb", "start": 90, "kind": "window",
                           "cues": [[88.0, "ok"], [90.0, "oh man so thirsty in here right now."]]}],
               "rejected": [], "rival_videos": []}
    assert any("the link starts 18 s before the quote" in p for p in _check(md, moments))
    md = md.replace("bbb&t=72s", "bbb&t=90s")
    assert not any("the link starts" in p for p in _check(md, moments))
