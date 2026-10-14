"""tl-brand-creator-connection probe: a fact counts as said again only where the
same words meet in the captions, never on a stray keyword. Invented data only."""
import sys
from pathlib import Path
S = Path(__file__).resolve().parents[1] / "skills" / "tl-brand-creator-connection" / "scripts"
sys.path.insert(0, str(S))
import authenticate as au, merge_pass as mp


def _frag(*cues):
    """A highlight fragment in the index's timed-text shape."""
    return "".join(f'<text start="{t}" dur="2.0">{x}</text>' for t, x in cues)


# ---- what is searched ----
def test_a_partner_phrase_counts_alone_but_a_general_one_does_not():
    assert au.specific_phrase("my fiance")
    assert au.specific_phrase("my sister")
    assert not au.specific_phrase("i hate")
    assert not au.specific_phrase("best friend")


def test_the_claims_first_word_and_platform_words_are_never_names():
    line = {"claim": "Has a cousin Marlo he calls his brother",
            "quote": "my brother marlo well he's really my cousin"}
    assert au.claim_names(line) == ["marlo"]
    assert au.claim_names({"claim": "Runs a marathon every month",
                           "quote": "I'm running a marathon every month"}) == []


def test_a_stop_word_brand_part_is_not_a_name():
    line = {"claim": "used to work at Home Bramblewood driving tractors",
            "quote": "I used to work at Home Bramblewood and drive the tractors"}
    assert au.claim_names(line) == ["bramblewood"]


def test_quote_terms_skip_filler_and_rank_rarest_first():
    line = {"quote": "I actually freaking bought a kayak with my own money"}
    freq = {"kayak": 1, "bought": 9, "money": 30}
    assert au.quote_terms(line, freq) == ["kayak", "bought", "money"]


def test_beside_a_name_a_word_in_most_uploads_is_dropped():
    line = {"claim": "calls his cousin Marlo his brother",
            "quote": "my brother marlo well he's really my cousin"}
    freq = {au.CORPUS_SIZE_KEY: 100, "brother": 40, "cousin": 2}
    phrase, name, terms, need = au.probe_plan(line, None, freq)
    assert (phrase, name, need) == (None, "marlo", 1)
    assert terms == ["cousin"]


def test_most_of_the_quote_must_be_said_again():
    line = {"claim": "runs a marathon every million followers",
            "quote": "I'm running a marathon every time I go up a million followers"}
    _p, _n, terms, need = au.probe_plan(line, None, {})
    assert len(terms) == 4 and need == 3


# ---- what counts as a hit ----
def test_words_minutes_apart_in_one_video_are_not_a_hit():
    frags = [_frag((10, "my kayak is the best"), (200, "I bought a new phone"))]
    assert au.near_hit(frags, None, None, ["kayak", "bought"], 2) is None


def test_words_close_together_are_a_hit():
    frags = [_frag((10, "I bought this kayak"), (14, "with my own money"))]
    hit = au.near_hit(frags, None, None, ["kayak", "bought", "money"], 2)
    assert hit is not None and hit[0] == 10


def test_a_name_that_is_also_a_word_needs_its_capital_in_cased_captions():
    frags = [_frag((5, "I watched the sun as it rose before our date"))]
    assert au.near_hit(frags, None, "rose", ["date"], 1) is None
    frags = [_frag((5, "date night with Rose tonight"))]
    assert au.near_hit(frags, None, "rose", ["date"], 1) is not None


def test_word_forms_meet():
    assert au._stem("jumping") == au._stem("jumps") == au._stem("jump")
    assert au._stem("boxes") == au._stem("box")
    assert au._stem("loves") == au._stem("love")
    assert au._stem("tractors") == au._stem("tractor")


# ---- what the probe decides ----
def _staged_line():
    return {"window": {"format_hint": "staged", "title": "How Long Can I Secretly Live In A Store?"},
            "verdict": {"claim": "lives in a store", "quote": "I live in this store now"}}


def test_a_fact_said_once_in_a_bit_stays_staged_only():
    p = {"probe": {"videos": 0, "non_staged_videos": 0, "own_videos": 1,
                   "own_non_staged_videos": 0, "recurring_videos": 1}}
    assert mp.staged_only(_staged_line(), p)


def test_a_fact_repeated_in_four_uploads_is_the_persons():
    p = {"probe": {"videos": 3, "non_staged_videos": 0, "own_videos": 1,
                   "own_non_staged_videos": 0, "recurring_videos": 4}}
    assert not mp.staged_only(_staged_line(), p)


def test_a_fact_whose_own_uploads_include_a_normal_one_is_the_persons():
    p = {"probe": {"videos": 0, "non_staged_videos": 0, "own_videos": 2,
                   "own_non_staged_videos": 1, "recurring_videos": 2}}
    assert not mp.staged_only(_staged_line(), p)


def test_girlfriend_then_fiancee_is_not_a_conflict():
    older = {"c": "c1", "domain": "relationships", "claim": "has a girlfriend named Marlo",
             "quote": "my girlfriend Marlo", "published": "2024-05-01"}
    newer = {"c": "c2", "domain": "relationships", "claim": "is engaged to Marlo",
             "quote": "I'm engaged to my fiancee Marlo", "published": "2026-02-01"}
    assert au.find_conflicts([older, newer]) == 0


def test_a_step_back_is_still_a_conflict():
    older = {"c": "c1", "domain": "relationships", "claim": "is married",
             "quote": "my husband and I", "published": "2023-01-01"}
    newer = {"c": "c2", "domain": "relationships", "claim": "has a boyfriend",
             "quote": "my boyfriend and I", "published": "2025-01-01"}
    assert au.find_conflicts([older, newer]) == 2


def test_a_personal_fact_said_once_in_a_stunt_is_not_staged_only():
    line = {"window": {"format_hint": "staged", "title": "I Tried Every Pizza In Town"},
            "verdict": {"claim": "their mom is named Ruth",
                        "quote": "my mom's name is Ruth she is the coolest lady I've ever met"}}
    p = {"probe": {"videos": 0, "non_staged_videos": 0, "own_videos": 1,
                   "own_non_staged_videos": 0, "recurring_videos": 1}}
    assert not mp.staged_only(line, p)


def test_an_opening_line_said_again_elsewhere_is_not_a_hook():
    line = {"window": {"format_hint": "staged"}, "members": [{"start": 1}]}
    p = {"probe": {"videos": 10, "non_staged_videos": 7, "recurring_videos": 11}}
    assert not mp.hook_only(line, ["v1"], p)
    assert mp.hook_only(line, ["v1"], {"probe": {"videos": 0, "non_staged_videos": 0, "recurring_videos": 1}})


def test_the_creators_own_childhood_is_not_a_child():
    import tier_hint
    assert not tier_hint.names_child("loved anything with wheels as a kid and was the first kid with roller skates")
    assert tier_hint.names_child("my son was the first kid in class to read")


def test_a_habit_span_starts_at_its_unbroken_run_not_a_stray_old_match():
    import authenticate
    assert authenticate.run_start(["2022-06-02", "2025-07-14", "2025-08-19", "2026-01-11"]) == "2025-07-14"
    assert authenticate.run_start([]) is None


# ---- what the review of the first version caught ----
def test_a_caption_tag_does_not_make_the_captions_cased():
    frags = [_frag((5, "[Music]"), (7, "date night with rose tonight"))]
    assert au.near_hit(frags, None, "rose", ["date"], 1) is not None


def test_a_camel_case_name_is_a_name_in_cased_captions():
    assert au._has_name("I saw McKenna today", "mckenna", True)
    assert au._has_name("ROSE is here", "rose", True)
    assert not au._has_name("the sun rose", "rose", True)


def test_accented_words_are_whole_words():
    assert au._words("mi fiancé vive en Bogotá") == ["mi", "fiancé", "vive", "en", "bogotá"]


def test_a_relationship_with_no_date_on_one_side_is_no_step_back():
    married = {"c": "c1", "domain": "relationships", "claim": "is married",
               "quote": "my husband and I", "published": ""}
    dating = {"c": "c2", "domain": "relationships", "claim": "has a girlfriend",
              "quote": "my girlfriend and I", "published": "2025-01-01"}
    assert au.find_conflicts([married, dating]) == 0


def test_someone_elses_first_kid_is_still_a_child():
    import tier_hint
    assert tier_hint.names_child("he was the first kid in his class to walk")
    assert not tier_hint.names_child("was the first kid on the block with a skateboard")
