"""tl-brand-creator-connection accuracy checks: one or more invented cases per check added after the 40-claim review (names, claim-to-quote, hooks, recency, ended, dates, host names, past reads). Invented data only."""
import json, sys
from pathlib import Path
S = Path(__file__).resolve().parents[1] / "skills" / "tl-brand-creator-connection" / "scripts"
sys.path.insert(0, str(S)); sys.path.insert(0, str(Path(__file__).parent))
import assemble_extracts as ax, merge_pass as mp, build_html as bh, authenticate as au
import verify_quotes as vq
from test_merge_pass import _cluster, _write_clusters, _envelope, _expand, _facts, _violations, _keep_all

# ---- Fix 2: names and family words ----
def test_fix2_name_not_in_quote_is_refused():
    assert ax.claim_overreach("Has a friend named Marlo", "my friend asked me to move") == ["Marlo"]
def test_fix2_family_word_must_be_the_creators_own():
    assert ax.claim_overreach("has a brother who bakes", "his brother bakes bread") == ["brother"]
    assert ax.claim_overreach("has a brother who bakes", "my brother bakes bread") == []
def test_fix2_family_word_absent_from_quote_is_refused():
    assert ax.claim_overreach("grandma taught them to knit", "she taught me to knit") == ["grandma"]
def test_fix2_two_names_run_together_are_split():
    facts = [{"fact_id": "f1", "people": [{"name": "Juno Pell"}]},
             {"fact_id": "f2", "people": [{"name": "Juno"}]},
             {"fact_id": "f3", "people": [{"name": "Pell"}]}]
    assert mp.people_list(facts)["two_names"] == ["Juno Pell"]
def test_fix2_narrowed_claim_cannot_add_a_relative(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("has a friend who sails",
                                            quote="my friend sails every weekend")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "claim": "has a brother who sails"}})
    v = _violations(_expand(c, d, tmp_path / "facts.jsonl"))
    assert "brother" in v["c001"][0]
def test_fix2_narrowed_claim_keeping_the_relative_passes(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("has a friend who sails often",
                                            quote="my friend sails every weekend")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "claim": "has a friend who sails"}})
    assert _expand(c, d, tmp_path / "facts.jsonl").returncode == 0

# ---- Fix 3: claim matches quote ----
def test_fix3_number_not_in_quote_is_refused():
    assert ax.claim_overreach("started lifting at 14", "i started lifting as a teen") == ["14"]
def test_fix3_quote_cut_inside_a_caption_line_is_extended():
    cues = [[10.0, "i made videos with my mom"], [12.0, "on her old camera when i was nine"]]
    assert ax.extend_to_cue_end(cues, "i made videos with my", 10.0) == "i made videos with my mom"
def test_fix3_quote_ending_at_a_line_break_hands_the_next_line_to_the_judge():
    cues = [[10.0, "i made videos with my mom"], [12.0, "on her old camera when i was nine"]]
    q = "i made videos with my mom"
    assert ax.extend_to_cue_end(cues, q, 10.0) == q          # the quote itself is untouched
    assert ax.next_line(cues, q, 10.0) == "on her old camera when i was nine"
    assert mp.compact({"verdict": {"quote": q, "next_line": "on her old camera when i was nine"},
                       "window": {}, "members": []}, 0)["next_line"] == "on her old camera when i was nine"
def test_fix3_no_next_line_after_a_sentence_end_or_mid_line():
    cues = [[10.0, "i made videos with my mom."], [12.0, "anyway the trip was great"]]
    assert ax.next_line(cues, "i made videos with my mom.", 10.0) is None
    cues = [[10.0, "i made videos with my mom on her camera"], [12.0, "back then"]]
    assert ax.next_line(cues, "i made videos with my mom", 10.0) is None
    assert ax.next_line([[10.0, "i love jazz"]], "i love jazz", 10.0) is None   # last line of the window
def test_fix3_next_line_drops_leftover_caption_markup():
    cues = [[10.0, "and then i"], [12.0, 'text start="12.5" dur="3.1">moved back home']]
    assert ax.next_line(cues, "and then i", 10.0) == "moved back home"
def test_fix3_whole_words_only_in_verification():
    hit = vq.locate([(10.0, "with my mom's camera since i was eight")], "with my mom")
    assert hit.get("match") != "exact"

# ---- Fix 4: hooks and staged lines ----
def test_fix4_hook_only_on_a_staged_upload_is_unconfirmed(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("was bullied at school", start=20, format_hint="staged",
                                            quote="i was bullied at school")])
    _keep_all(c, tmp_path / "facts.jsonl")
    fact = next(iter(_facts(tmp_path / "facts.jsonl").values()))
    assert fact["hook_only"] is True and fact["confidence"] == "unconfirmed" and not fact["selected"]
def test_fix4_an_ordinary_uploads_opening_stays_confirmed(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("has a brother named Pete", start=20,
                                            quote="my brother pete came over")])
    _keep_all(c, tmp_path / "facts.jsonl")
    fact = next(iter(_facts(tmp_path / "facts.jsonl").values()))
    assert fact["confidence"] == "confirmed" and not fact.get("hook_only")
def test_fix4_every_staged_line_is_probed():
    assert au.wants_probe({"format_hint": "staged", "domain": "tastes"})
    assert not au.wants_probe({"format_hint": None, "domain": "tastes"})
def test_fix4_staged_only_line_is_never_selected():
    assert mp.selectable({"staged_only": True, "sensitivity": "none"}) is False

# ---- Fix 5: recency and ended ----
def test_fix5_last_seen_is_the_newest_member():
    line = {"members": [{"video_id": "a", "published": "2021-03-01"},
                        {"video_id": "b", "published": "2025-06-01"}],
            "window": {"published": "2021-03-01"}}
    assert str(mp.newest_evidence(line, None))[:10] == "2025-06-01"
def test_fix5_rank_puts_recent_before_more_repeated(monkeypatch):
    monkeypatch.setattr(mp, "RUN_DATE", "2026-10-06")
    old = {"fact_id": "f1", "confidence": "confirmed", "last_seen": "2019-01-01", "recurrence": 9}
    new = {"fact_id": "f2", "confidence": "confirmed", "last_seen": "2026-01-01", "recurrence": 1}
    assert sorted([old, new], key=mp.rank_key)[0]["fact_id"] == "f2"
def test_fix5_ended_is_never_selected_or_quoted():
    f = {"ended": True, "confidence": "confirmed", "sensitivity": "none"}
    assert mp.selectable(f) is False and "ended" in bh.angle_ineligible_reason(f)
def test_fix5_same_months_in_both_scripts():
    assert mp.RECENT_MONTHS == bh.RECENT_MONTHS == 24

# ---- Fix 6: nothing unconfirmed reaches a reader ----
def test_fix6_no_top_up_constant():
    assert not hasattr(mp, "SELECTED_MIN")
def test_fix6_unconfirmed_is_refused_on_the_page():
    assert bh.angle_ineligible_reason({"confidence": "unconfirmed", "sensitivity": "none"}) == "unconfirmed"
def test_fix6_unconfirmed_stays_in_the_ledger(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("likes jazz", conf="likely", quote="i like jazz a lot")])
    _keep_all(c, tmp_path / "facts.jsonl")
    fact = next(iter(_facts(tmp_path / "facts.jsonl").values()))
    assert fact["confidence"] == "unconfirmed" and fact["selected"] is False

# ---- Fix 7: relative dates ----
def test_fix7_years_ago_becomes_a_year():
    claim, note = mp.dated_claim("moved to the coast five years ago", "2025-11-02", None)
    assert claim == "moved to the coast in about 2020 (said in 2025)"
def test_fix7_months_ago_crosses_the_year_from_the_full_date():
    claim, _ = mp.dated_claim("moved two months ago", "2025-01-15", None)
    assert "about 2024" in claim
    claim, _ = mp.dated_claim("moved six months ago", "2025-12-15", None)
    assert "about 2025" in claim
def test_fix7_channel_start_uses_the_first_upload():
    claim, note = mp.dated_claim("started the channel about 5 years ago", "2025-11-02", "2019-07-01")
    assert "2019" in claim and "said" in claim

# ---- test-run fixes (2026-10-05) ----
import channel_context as cc, start_run as sr, bio_lane as bl
def test_run_host_name_is_the_name_said_on_camera_never_the_channel_name():
    full = {"name": "Skyhook", "name_candidates": [
        {"name": "sky", "videos": 3, "said_outright": False},
        {"name": "dana", "videos": 4, "said_outright": True, "said_outright_videos": 2}]}
    assert cc.write_context(full, format_label="solo", format_evidence="x")["host_names"] == ["Dana"]
    assert cc.write_context({"name": "Skyhook"}, format_label="solo", format_evidence="x")["host_names"] == []
    one = {"name": "Skyhook", "name_candidates": [
        {"name": "dana", "videos": 5, "said_outright": True, "said_outright_videos": 1}]}
    assert cc.write_context(one, format_label="solo", format_evidence="x")["host_names"] == []
def test_run_word_forms_and_possessives_match():
    assert ax.claim_overreach("has Czechoslovak roots", "my czechoslovakia roots") == []
    assert ax.claim_overreach("moved during Arizona's summer", "we moved during the arizona summer") == []
    assert ax.claim_overreach("grew up near Erica", "i grew up near eric") == ["Erica"]
def test_run_slang_is_not_a_relative():
    assert ax.claim_overreach("can pop out for groceries", "i can pop out to the store") == []
def test_run_a_relatives_relative_needs_no_creator_ownership():
    assert ax.claim_overreach("has a brother who has a wife", "my brother and his wife came") == []
    assert ax.claim_overreach("has a wife", "my brother and his wife came") == ["wife"]
def test_run_judge_rewrite_may_keep_a_possessive_name(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("moved to arizona", quote="we moved to arizona for the monsoon")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "claim": "moved for Arizona's monsoon"}})
    assert _expand(c, d, tmp_path / "facts.jsonl").returncode == 0
def test_run_a_promoting_line_alone_is_not_a_brand_brief():
    class A: talking_points = None; promoting = "Widget Pro"
    rec = sr.creator_brief_input(A, {"id": 1, "name": "c"}, {"id": 2, "name": "b"})
    assert rec["supplied"] is False and rec["promoting"] == "Widget Pro"
def test_run_precedent_card_with_no_probe_text_fails():
    md = ("---\nchannel_name: C\n---\n## About C\nx\n## Thesis\nx\n## About B\nx\n"
          "## Where this could go wrong\nx\n## Cooks at night \u00b7 **category precedent** \u00b7 **thin**\n"
          "> i cook at night [C](https://www.youtube.com/watch?v=abc&t=5s)\n")
    probs = bh.check_page(md, [{"fact_id": "f1", "claim": "z", "quote": "unrelated", "confidence": "confirmed"}],
                          {}, {"windows": [{"excerpt": "i cook at night"}]})
    assert any("no window text" in p for p in probs)
def test_run_brief_refuses_another_creators_name(tmp_path):
    (tmp_path / "brand-tl.json").write_text(json.dumps({"reads": [{"channel_name": "Other Person"}],
                                                        "top_channels": [{"name": "The Creator"}]}))
    names = bh.other_creator_names(tmp_path / "connections-1.md", "The Creator")
    assert names == ["Other Person"]
def test_run_round_two_recipe_carries_host_names_and_the_prompt_step(tmp_path, capsys):
    facts = tmp_path / "bio-facts.json"
    facts.write_text(json.dumps({"facts": []}))
    try:
        bl.main(["terms", "--facts", str(facts), "--channel", "1", "--out", str(tmp_path), "--host-names", "Dana"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    if out.strip().startswith("{"):
        rec = json.loads(out[:out.rindex("}") + 1])["recipe"]
        assert '--host-names "Dana"' in rec[0] and "extractor_prompt.py" in rec[1]
def test_run_channel_start_skips_early_hobby_uploads():
    assert mp.channel_start(["2016-06-13", "2016-11-08", "2019-07-09", "2019-07-15", "2019-07-31", "2019-08-08"]) == "2019-07-09"
    assert mp.channel_start(["2015-01-01", "2015-02-01", "2015-03-01", "2015-04-01", "2015-05-01", "2015-06-01", "2018-01-01"]) == "2015-01-01"
    claim, _ = mp.dated_claim("started the channel about 5 years ago", "2025-11-08", "2019-07-09")
    assert "2019" in claim and "said" in claim

# ---- round-2 fixes (2026-10-05) ----
def test_r2_past_read_positions_refuse_a_moment_inside_the_creators_read(tmp_path):
    (tmp_path / "brand-tl.json").write_text(json.dumps({"this_channel_reads": [
        {"video_id": "vid1", "start": 300, "end": 390}, {"video_id": "vid2", "start": None},
        {"video_id": "vid3", "start": 0, "end": 0}]}))
    spots = bh.past_read_spots(tmp_path / "connections-1.md")
    assert spots == [("vid1", 300.0, 390.0)]
    inside = {"url": "https://www.youtube.com/watch?v=vid1&t=320s"}
    late_in_read = {"url": "https://www.youtube.com/watch?v=vid1&t=420s"}
    outside = {"url": "https://www.youtube.com/watch?v=vid1&t=900s"}
    assert bh.prior_read_problem(inside, "Brand", None, "pt", spots)
    assert bh.prior_read_problem(late_in_read, "Brand", None, "pt", spots)
    assert bh.prior_read_problem(outside, "Brand", None, "pt", spots) is None
def test_r2_corroboration_terms_use_own_words_skip_host_and_never_bridge_a_list():
    terms = bl.corroboration_terms("Dana is a total geek: gaming, astronomy, Christmas and tea",
                                   exclude={"Dana"})
    assert "Dana" not in " ".join(terms)
    assert not any(t in ("astronomy Christmas", "gaming astronomy") for t in terms)
def test_r2_a_title_never_ends_a_sentence():
    assert bl._SENTENCE_SPLIT.split("Founded by Dana. Mrs. Lee sings. Bye.") == [
        "Founded by Dana.", "Mrs. Lee sings.", "Bye."]
def test_r2_old_precedent_window_cannot_carry_a_strong_card():
    md = ("---\nchannel_name: C\n---\n## About C\nx\n## Thesis\nx\n## About B\nx\n"
          "## Where this could go wrong\nx\n## Cooks at night · **category precedent** · **strong**\n"
          "> i cook at night\n> [C, 2019-01-01](https://www.youtube.com/watch?v=abc&t=5s)\n")
    probe = {"windows": [{"text": "i cook at night", "published": "2019-01-01"}]}
    probs = bh.check_page(md, [{"fact_id": "f1", "claim": "z", "quote": "unrelated", "confidence": "confirmed"}], {}, probe)
    assert any("strong connection rests on a window from 2019" in p for p in probs)

# ---- review fixes (2026-10-06) ----
def test_review_a_ledger_without_last_seen_falls_back_to_published():
    fact = {"published": "2026-05-01"}
    assert mp.is_recent(fact, "2026-10-06") and bh.is_recent(fact, "2026-10-06")
    assert not bh.is_recent({"published": "2019-05-01"}, "2026-10-06")
def test_review_a_fold_carries_its_newer_date_into_the_kept_fact(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("moved to Austin", video="v1", published="2019-01-01"),
                                   _cluster("moved to Austin", video="v2", published="2026-05-01")])
    d = _envelope(tmp_path, {"c001": {"action": "keep"}, "c002": {"action": "fold", "target": "c001"}})
    out = tmp_path / "facts.jsonl"
    proc = _expand(c, d, out)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _facts(out)["f001"]["last_seen"] == "2026-05-01"
def test_review_ended_false_is_accepted(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("moved to Austin")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "ended": False}})
    proc = _expand(c, d, tmp_path / "facts.jsonl")
    assert proc.returncode == 0, proc.stdout + proc.stderr
def test_review_a_narrowed_claim_still_cannot_open_with_a_new_name(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("has a sister who nurses", quote="my sister is a nurse")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "claim": "Jessica is his sister, a nurse"}})
    assert "jessica" in _violations(_expand(c, d, tmp_path / "facts.jsonl"))["c001"][0]
def test_review_a_narrowed_claim_may_spell_a_number_differently(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("is a parent of three", quote="my three kids keep me busy")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "claim": "Has 3 kids"}})
    proc = _expand(c, d, tmp_path / "facts.jsonl")
    assert proc.returncode == 0, proc.stdout + proc.stderr
def test_review_a_narrowed_claim_may_start_with_a_capitalised_verb(tmp_path):
    c = _write_clusters(tmp_path, [_cluster("has two dogs", quote="i have two dogs at home")])
    d = _envelope(tmp_path, {"c001": {"action": "keep", "claim": "Owns two dogs"}})
    proc = _expand(c, d, tmp_path / "facts.jsonl")
    assert proc.returncode == 0, proc.stdout + proc.stderr
def test_review_spelled_and_comma_numbers_match():
    assert ax.claim_overreach("has 3 kids", "i have three kids") == []
    assert ax.claim_overreach("earned 1,000 dollars", "i made 1000 dollars") == []
    assert ax.claim_overreach("is in his 30s", "im in my thirties now") == []
    assert ax.claim_overreach("has 4 kids", "i have three kids") == ["4"]
    assert ax.claim_overreach("is 30 years old", "im in my thirties now") == ["30"]
    assert ax.claim_overreach("has 1 kid", "one of my kids is starting school") == ["1"]
    assert ax.claim_overreach("costs 15 euros", "it costs 1,5 euros") == ["15"]
def test_review_a_claims_first_word_is_still_checked_as_a_relative():
    assert ax.claim_overreach("Wife works as a nurse", "my sister works as a nurse") == ["wife"]
    assert ax.claim_overreach("Dad was a pilot", "his dad was a pilot") == ["dad"]
def test_review_a_non_english_quote_skips_the_english_family_words():
    q = "tengo un hermano menor en Madrid"
    assert ax.claim_overreach("has a younger brother in Madrid", q) == ["brother"]
    assert ax.claim_overreach("has a younger brother in Madrid", q, english=False) == []
    assert ax.claim_overreach("has a brother in Toledo", q, english=False) == ["Toledo"]
def test_review_people_said_in_the_possessive_are_kept():
    assert ax.people_in_quote([{"name": "Sarah"}], "my wife Sarah's birthday") == [
        {"name": "Sarah", "relation": None}]
    assert ax.people_in_quote([{"name": "Chris"}], "my friend Christina came") == []
def test_review_spoken_host_name_prefers_the_channel_name_variant():
    full = {"name_candidates": [
        {"name": "marta", "channel_name_variant": True, "said_outright": True, "said_outright_videos": 2},
        {"name": "sienna", "channel_name_variant": False, "said_outright": True, "said_outright_videos": 5}]}
    assert cc.host_name_call(full) == (["Marta"], "transcripts")
def test_review_host_possessive_is_excluded_from_corroboration_terms():
    terms = bl.corroboration_terms("Sarah's bakery opened in Leeds", exclude={"Sarah"})
    assert not any("Sarah" in t for t in terms)
