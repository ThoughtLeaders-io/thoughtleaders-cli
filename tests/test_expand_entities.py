"""Tests for the tl-keyword-research expand_entities.py script.

The script lives under skills/ (not the package), so we load it by path. It does
no network or subprocess work, so nothing needs mocking — only stdin/stdout.
"""
import importlib.util
import io
import json
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts" / "expand_entities.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("kw_expand", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ee = _load()


class TestNumberWords:
    def test_ones_and_teens(self):
        assert ee.number_word(5) == "five"
        assert ee.number_word(13) == "thirteen"

    def test_tens_and_compounds(self):
        assert ee.number_word(20) == "twenty"
        assert ee.number_word(21) == "twenty one"   # space, not hyphen (hyphen splits)

    def test_spell_out_only_small_standalone_ints(self):
        assert ee.spell_out_numbers("fable 5") == "fable five"
        assert ee.spell_out_numbers("cannes lions 2026") is None   # 4-digit left alone
        assert ee.spell_out_numbers("gpt 4.8") is None             # decimal left alone
        assert ee.spell_out_numbers("annuity") is None             # no number


class TestSolidAndVariants:
    def test_solid_strips_spaces_and_hyphens(self):
        assert ee.solid("fable 5") == "fable5"
        assert ee.solid("fable-5") == "fable5"
        assert ee.solid("annuity") == "annuity"

    def test_variants_emit_solid_and_spelled_not_hyphen(self):
        # 'fable-5' tokenizes identically to 'fable 5' so it must NOT be a 3rd form
        assert ee.text_variants("fable 5") == ["fable 5", "fable5", "fable five"]

    def test_variants_single_word_is_itself(self):
        assert ee.text_variants("annuity") == ["annuity"]

    def test_variants_multiword_no_number(self):
        assert ee.text_variants("cannes lions") == ["cannes lions", "canneslions"]

    def test_variants_four_digit_year_not_spelled(self):
        assert ee.text_variants("cannes lions 2026") == ["cannes lions 2026", "canneslions2026"]

    def test_hashtag_form(self):
        # case is preserved (ES lowercases at match time, so this is cosmetic)
        assert ee.hashtag_form("Cannes Lions") == "#CannesLions"
        assert ee.hashtag_form("  ") is None


class TestGrouping:
    def test_quote_only_multiword(self):
        assert ee._quote("fable5") == "fable5"
        assert ee._quote("fable 5") == '"fable 5"'

    def test_group_query_or_join(self):
        assert ee.group_query(["fable 5", "fable5"]) == '("fable 5" | fable5)'

    def test_candidate_single_is_phrase(self):
        assert ee._candidate_from_forms(["annuity"], "annuity") == {"phrase": "annuity", "label": "annuity"}

    def test_candidate_multi_is_sqs(self):
        c = ee._candidate_from_forms(["cannes lions", "canneslions"], "Cannes Lions")
        assert c == {"sqs": '("cannes lions" | canneslions)', "label": "Cannes Lions"}

    def test_candidate_empty_is_none(self):
        assert ee._candidate_from_forms([], "x") is None


class TestExpand:
    def test_entity_family_to_probe_candidate(self):
        resolver = {"entities": [{"name": "Cannes Lions Grand Prix", "kind": "category"}]}
        out = ee.expand(resolver, existing=[], max_insider=40)
        assert out["probe_candidates"] == [
            {"sqs": '("Cannes Lions Grand Prix" | CannesLionsGrandPrix)', "label": "Cannes Lions Grand Prix"}
        ]
        assert out["families"][0]["kind"] == "category"
        assert "#CannesLionsGrandPrix" in out["hashtags"]

    def test_dedupe_against_existing_drops_form(self):
        resolver = {"entities": [{"name": "cannes lions", "kind": "event"}]}
        out = ee.expand(resolver, existing=["cannes lions"], max_insider=40)
        # the spaced form is already known; only the solid token survives -> phrase candidate
        assert out["probe_candidates"] == [{"phrase": "canneslions", "label": "cannes lions"}]
        assert "cannes lions" in out["deduped"]

    def test_fully_deduped_family_yields_no_candidate(self):
        resolver = {"entities": [{"name": "annuity", "kind": "other"}]}
        out = ee.expand(resolver, existing=["Annuity"], max_insider=40)   # case-insensitive
        assert out["probe_candidates"] == []
        assert out["deduped"] == ["annuity"]

    def test_insider_terms_capped(self):
        resolver = {"insider_terms": [f"term{i}" for i in range(50)]}
        out = ee.expand(resolver, existing=[], max_insider=10)
        assert len(out["families"]) == 10
        assert out["counts"]["families"] == 10

    def test_alias_pairs_into_one_group(self):
        resolver = {"aliases": [{"old": "Cannes Advertising Festival", "new": "Cannes Lions", "since": "2011"}]}
        out = ee.expand(resolver, existing=[], max_insider=40)
        assert len(out["aliases"]) == 1
        cand = out["probe_candidates"][0]
        assert cand["label"] == "rename: Cannes Advertising Festival -> Cannes Lions"
        assert cand["sqs"].startswith("(") and "|" in cand["sqs"]
        # both era names present in the group (case preserved)
        assert "Cannes Advertising Festival" in cand["sqs"]
        assert "Cannes Lions" in cand["sqs"]

    def test_collisions_pass_through(self):
        resolver = {"collisions": [{"term": "cannes", "other_meaning": "Cannes Film Festival"}]}
        out = ee.expand(resolver, existing=[], max_insider=40)
        assert out["collisions"] == [{"term": "cannes", "other_meaning": "Cannes Film Festival"}]

    def test_cross_family_dedup_no_repeat_probes(self):
        # same name twice -> probed once
        resolver = {"entities": [{"name": "Titanium Lion"}], "insider_terms": ["Titanium Lion"]}
        out = ee.expand(resolver, existing=[], max_insider=40)
        labels = [c.get("label") for c in out["probe_candidates"]]
        assert labels.count("Titanium Lion") == 1


class TestMainIO:
    def _run(self, monkeypatch, capsys, stdin_obj, argv):
        monkeypatch.setattr(ee.sys, "stdin", io.StringIO(json.dumps(stdin_obj)))
        monkeypatch.setattr(ee.sys, "argv", argv)
        ee.main()
        return capsys.readouterr().out

    def test_default_emits_full_object(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys,
                        {"entities": [{"name": "Cannes Lions"}]},
                        ["expand_entities.py"])
        obj = json.loads(out)
        assert "probe_candidates" in obj and "families" in obj and "counts" in obj

    def test_probe_batch_emits_array_only(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys,
                        {"entities": [{"name": "Cannes Lions"}]},
                        ["expand_entities.py", "--probe-batch"])
        arr = json.loads(out)
        assert isinstance(arr, list)
        assert arr == [{"sqs": '("Cannes Lions" | CannesLions)', "label": "Cannes Lions"}]

    def test_existing_flag_dedupes(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys,
                        {"entities": [{"name": "Cannes Lions"}]},
                        ["expand_entities.py", "--probe-batch", "--existing", "cannes lions"])
        arr = json.loads(out)
        assert arr == [{"phrase": "CannesLions", "label": "Cannes Lions"}]

    def test_non_object_stdin_rejected(self, monkeypatch, capsys):
        monkeypatch.setattr(ee.sys, "stdin", io.StringIO("[1,2,3]"))
        monkeypatch.setattr(ee.sys, "argv", ["expand_entities.py"])
        with pytest.raises(SystemExit):
            ee.main()
