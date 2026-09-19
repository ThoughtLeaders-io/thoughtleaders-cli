"""Tests for classify_channels.py — merging channel verdicts onto the table.

No ES here: the script only reads evidence.py's JSON, the verdict arrays you
write, the intensity tiers and an optional ranking.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "tl-keyword-research" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"kw_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cc():
    return _load("classify_channels")


def write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def ev_channel(cid, **kw):
    base = {"channel_id": cid, "name": f"ch{cid}", "tier": "recurring",
            "matching_uploads": 5, "recent_matching_uploads": 2, "topic_share": 0.3,
            "evidence": [{"video_id": f"v{cid}", "title": "T", "date": "2026-01-01",
                          "url": "u", "field": "summary", "snippet": "s"}]}
    base.update(kw)
    return base


def evidence_file(tmp_path, channels, *, missing=None, unresolved=None, failed=None):
    return write(tmp_path, "evidence.json",
                 {"channels": channels, "missing": missing or [],
                  "unresolved": unresolved or [], "failed": failed or [],
                  "requested": len(channels) + len(missing or []), "fetched": len(channels)})


# Stderr of the last run_classify call — capsys can only be drained once, so the
# guidance the script prints alongside exit 2 is kept here for the test that wants it.
LAST_STDERR = {"text": ""}


def run_classify(cc, monkeypatch, capsys, argv):
    monkeypatch.setattr(cc.sys, "argv", ["classify_channels.py", *argv])
    code = 0
    try:
        cc.main()
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    LAST_STDERR["text"] = captured.err
    return (json.loads(captured.out) if captured.out.strip() else None), code


@pytest.fixture
def world(tmp_path):
    """Four channels across three tiers, with intensity + ranking beside them."""
    channels = [
        ev_channel(1, tier="core", matching_uploads=14, topic_share=0.62,
                   sponsorability={"is_msn": True, "is_tpp": False, "has_outreach_email": False}),
        ev_channel(2, tier="recurring", matching_uploads=9,
                   sponsorability={"is_msn": False, "is_tpp": True, "has_outreach_email": False}),
        ev_channel(3, tier="recurring", matching_uploads=12,
                   sponsorability={"is_msn": False, "is_tpp": False, "has_outreach_email": False}),
        ev_channel(4, tier="one_off", matching_uploads=1),
    ]
    return {
        "evidence": evidence_file(tmp_path, channels, missing=[5], unresolved=[6],
                                  failed=[{"chunk_index": 2, "channel_ids": [7],
                                           "kind": "timeout", "reason": "timed out"}]),
        "intensity": write(tmp_path, "intensity.json", {"channels": [
            {"channel_id": c, "name": f"ch{c}", "tier": "recurring"} for c in (1, 2, 3, 4, 5, 6, 7, 8)
        ]}),
        "tmp": tmp_path,
    }


# ------------------------------------------------------------- happy path

class TestApply:
    def test_all_four_verdicts_and_tier_grouping(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json", [
            {"channel_id": 1, "verdict": "on_topic", "evidence_quote": "«cannes»"},
            {"channel_id": 2, "verdict": "mixed", "note": "incidental"},
            {"channel_id": 3, "verdict": "off_topic"},
            {"channel_id": 4, "verdict": "unknown"},
        ])
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert code == 0
        assert out["judged"] == 4
        assert out["verdicts"] == {"on_topic": 1, "mixed": 1, "off_topic": 1, "unknown": 1}
        assert [c["channel_id"] for c in out["channels"]] == [1, 2]
        assert out["channels"][0]["evidence_quote"] == "«cannes»"
        assert out["channels"][1]["note"] == "incidental"
        assert [c["channel_id"] for c in out["excluded"]] == [3]
        assert [c["channel_id"] for c in out["not_validated"]["unknown"]] == [4]
        assert out["by_tier"] == {"core": {"on_topic": 1}, "recurring": {"mixed": 1, "off_topic": 1},
                                  "one_off": {"unknown": 1}}
        assert out["missing"] == []
        assert "confidence" not in out["channels"][0]

    def test_rows_sort_by_tier_then_matching_uploads(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json",
                         [{"channel_id": c, "verdict": "on_topic"} for c in (1, 2, 3, 4)])
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert code == 0
        assert [c["channel_id"] for c in out["channels"]] == [1, 3, 2, 4]

    def test_not_validated_buckets(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json",
                         [{"channel_id": c, "verdict": "on_topic"} for c in (1, 2, 3, 4)])
        out, _ = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        nv = out["not_validated"]
        assert nv["no_evidence"] == [5] and nv["unresolved"] == [6] and nv["failed"] == [7]
        assert nv["not_fetched"] == [8]  # in intensity, never requested

    def test_sponsorability_summary_counts_kept_rows_only(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json", [
            {"channel_id": 1, "verdict": "on_topic"}, {"channel_id": 2, "verdict": "mixed"},
            {"channel_id": 3, "verdict": "off_topic"}, {"channel_id": 4, "verdict": "unknown"}])
        out, _ = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert out["sponsorability_summary"] == {"reachable": 2, "msn": 1, "tpp": 1}

    def test_ranking_merges_as_rank(self, cc, monkeypatch, capsys, world):
        ranking = write(world["tmp"], "rank.json",
                        {"channels": [{"channel_id": 2}, {"channel_id": 1}]})
        verdicts = write(world["tmp"], "v.json",
                         [{"channel_id": c, "verdict": "on_topic"} for c in (1, 2, 3, 4)])
        out, _ = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"], "--ranking", ranking])
        ranks = {c["channel_id"]: c["rank"] for c in out["channels"]}
        assert ranks[1] == 2 and ranks[2] == 1 and ranks[4] is None

    def test_rank_is_null_without_a_ranking_file(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json", [{"channel_id": 1, "verdict": "on_topic"}])
        out, _ = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"], "--allow-missing"])
        assert out["channels"][0]["rank"] is None

    def test_adjacent_terms_pool_case_insensitively(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json", [
            {"channel_id": 1, "verdict": "on_topic", "adjacent_terms": ["Young Lions", " grand prix "]},
            {"channel_id": 2, "verdict": "mixed", "adjacent_terms": ["young lions"]},
            {"channel_id": 3, "verdict": "off_topic", "adjacent_terms": ["young lions", ""]},
            {"channel_id": 4, "verdict": "unknown"}])
        out, _ = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert out["adjacent_terms"] == [{"term": "young lions", "channels": [1, 2, 3]},
                                         {"term": "grand prix", "channels": [1]}]


# ------------------------------------------------------------- validation

class TestValidation:
    def _one(self, cc, monkeypatch, capsys, world, items):
        verdicts = write(world["tmp"], "bad.json", items)
        return run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])

    def test_not_an_array_is_fatal(self, cc, monkeypatch, capsys, world):
        _, code = self._one(cc, monkeypatch, capsys, world, {"channel_id": 1, "verdict": "on_topic"})
        assert "bare JSON array" in str(code)

    def test_unknown_channel_id_lists_the_judged_channels(self, cc, monkeypatch, capsys, world):
        _, code = self._one(cc, monkeypatch, capsys, world,
                            [{"channel_id": 99, "verdict": "on_topic"}])
        assert "not in the evidence file" in str(code) and "[1, 2, 3, 4]" in str(code)

    def test_bad_verdict_is_fatal(self, cc, monkeypatch, capsys, world):
        _, code = self._one(cc, monkeypatch, capsys, world,
                            [{"channel_id": 1, "verdict": "maybe"}])
        assert "verdict must be one of" in str(code)

    def test_non_integer_channel_id_is_fatal(self, cc, monkeypatch, capsys, world):
        _, code = self._one(cc, monkeypatch, capsys, world,
                            [{"channel_id": "1", "verdict": "on_topic"}])
        assert "channel_id must be an integer" in str(code)

    def test_conflicting_duplicate_in_one_file_is_fatal(self, cc, monkeypatch, capsys, world):
        _, code = self._one(cc, monkeypatch, capsys, world,
                            [{"channel_id": 1, "verdict": "on_topic"},
                             {"channel_id": 1, "verdict": "off_topic"}])
        assert "judged twice in the same file" in str(code)

    def test_identical_repeat_in_one_file_is_fine(self, cc, monkeypatch, capsys, world):
        out, code = self._one(cc, monkeypatch, capsys, world,
                              [{"channel_id": 1, "verdict": "on_topic"},
                               {"channel_id": 1, "verdict": "on_topic"}])
        assert code == 2  # only channel 1 judged; the other three are missing
        assert out["verdicts"]["on_topic"] == 1

    def test_adjacent_terms_must_be_strings(self, cc, monkeypatch, capsys, world):
        _, code = self._one(cc, monkeypatch, capsys, world,
                            [{"channel_id": 1, "verdict": "on_topic", "adjacent_terms": [3]}])
        assert "adjacent_terms must be a list of strings" in str(code)

    def test_later_files_override_earlier_ones(self, cc, monkeypatch, capsys, world):
        first = write(world["tmp"], "a.json",
                      [{"channel_id": c, "verdict": "on_topic"} for c in (1, 2, 3, 4)])
        second = write(world["tmp"], "b.json", [{"channel_id": 3, "verdict": "off_topic"}])
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", first,
            "--verdicts", second, "--intensity", world["intensity"]])
        assert code == 0
        assert [c["channel_id"] for c in out["excluded"]] == [3]
        assert [c["channel_id"] for c in out["channels"]] == [1, 2, 4]


# ---------------------------------------------------------------- coverage

class TestCoverage:
    def test_missing_verdicts_exit_2_and_become_unknown(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json", [{"channel_id": 1, "verdict": "on_topic"}])
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert code == 2
        assert out["missing"] == [2, 3, 4]
        unknown = out["not_validated"]["unknown"]
        assert [r["channel_id"] for r in unknown] == [3, 2, 4]
        assert all(r["note"] == "no verdict" for r in unknown)
        assert "no verdict" in LAST_STDERR["text"]

    def test_allow_missing_exits_zero(self, cc, monkeypatch, capsys, world):
        verdicts = write(world["tmp"], "v.json", [{"channel_id": 1, "verdict": "on_topic"}])
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"], "--allow-missing"])
        assert code == 0 and out["missing"] == [2, 3, 4]
        assert out["verdicts"]["unknown"] == 3


# ------------------------------------------------------- compact TSV verdicts

def write_text(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestTsvVerdicts:
    def test_tsv_happy_path(self, cc, monkeypatch, capsys, world):
        verdicts = write_text(world["tmp"], "v.tsv",
                              "# channel verdicts\n"
                              "\n"
                              "1\ton_topic\t…«Cannes Lions» Grand Prix…\tyoung lions, brand film\n"
                              "2\tmixed\n"
                              "3\toff_topic\tan unrelated lion\n"
                              "4\tunknown\n")
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert code == 0
        assert out["verdicts"] == {"on_topic": 1, "mixed": 1, "off_topic": 1, "unknown": 1}
        assert [c["channel_id"] for c in out["channels"]] == [1, 2]
        assert out["channels"][0]["evidence_quote"] == "…«Cannes Lions» Grand Prix…"
        assert out["excluded"][0]["evidence_quote"] == "an unrelated lion"
        assert out["adjacent_terms"] == [{"term": "brand film", "channels": [1]},
                                         {"term": "young lions", "channels": [1]}]

    def test_bad_verdict_names_the_line_number(self, cc, monkeypatch, capsys, world):
        verdicts = write_text(world["tmp"], "bad.tsv",
                              "# header\n"
                              "1\ton_topic\n"
                              "\n"
                              "2\tmaybe\n")
        _, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"]])
        assert "bad.tsv:4" in str(code) and "verdict must be one of" in str(code)

    def test_json_and_tsv_files_mix(self, cc, monkeypatch, capsys, world):
        as_json = write(world["tmp"], "first.json", [
            {"channel_id": 1, "verdict": "on_topic"},
            {"channel_id": 2, "verdict": "off_topic"},
        ])
        as_tsv = write_text(world["tmp"], "second.tsv", "3\tmixed\n4\ton_topic\n")
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"],
            "--verdicts", as_json, "--verdicts", as_tsv,
            "--intensity", world["intensity"]])
        assert code == 0
        assert out["judged"] == 4 and out["missing"] == []
        assert [c["channel_id"] for c in out["channels"]] == [1, 3, 4]
        assert [c["channel_id"] for c in out["excluded"]] == [2]


class TestUnjudgeableChannels:
    """evidence.py lists EVERY requested channel under `channels` — including the
    ones it could not read. Those carry nothing to judge, so they are not a
    coverage gap and are reported once, under the bucket that explains them."""

    def _world(self, tmp_path):
        channels = [ev_channel(1), ev_channel(2, evidence=[]), ev_channel(3, evidence=[]),
                    ev_channel(4, evidence=[])]
        return (evidence_file(tmp_path, channels, missing=[2], unresolved=[3],
                              failed=[{"chunk_index": 0, "channel_ids": [4], "kind": "error",
                                       "reason": "boom"}]),
                write(tmp_path, "intensity.json", {"channels": [{"channel_id": 1}]}),
                write(tmp_path, "v.json", [{"channel_id": 1, "verdict": "on_topic"}]))

    def test_exit_zero_and_a_single_placement(self, cc, monkeypatch, capsys, tmp_path):
        ev_path, intensity, verdicts = self._world(tmp_path)
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", ev_path, "--verdicts", verdicts,
            "--intensity", intensity])
        assert code == 0 and out["missing"] == []
        nv = out["not_validated"]
        assert nv["no_evidence"] == [2] and nv["unresolved"] == [3] and nv["failed"] == [4]
        assert [r["channel_id"] for r in nv["unknown"]] == []   # not also reported here
        assert out["judged"] == 1 and out["verdicts"]["unknown"] == 0
        assert [c["channel_id"] for c in out["channels"]] == [1]

    def test_an_explicit_verdict_on_one_is_still_honoured(self, cc, monkeypatch, capsys,
                                                          tmp_path):
        ev_path, intensity, _ = self._world(tmp_path)
        verdicts = write(tmp_path, "v2.json", [{"channel_id": 1, "verdict": "on_topic"},
                                               {"channel_id": 2, "verdict": "off_topic"}])
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", ev_path, "--verdicts", verdicts,
            "--intensity", intensity])
        assert code == 0 and [c["channel_id"] for c in out["excluded"]] == [2]


class TestTsvBoundedSplit:
    def test_the_last_column_keeps_its_embedded_tabs(self, cc, monkeypatch, capsys, world):
        verdicts = write_text(world["tmp"], "tabby.tsv",
                              "1\ton_topic\t«cannes»\tyoung lions\ta note\twith a tab\n")
        out, code = run_classify(cc, monkeypatch, capsys, [
            "--apply", "--evidence", world["evidence"], "--verdicts", verdicts,
            "--intensity", world["intensity"], "--allow-missing"])
        assert code == 0
        assert out["channels"][0]["note"] == "a note\twith a tab"
        assert out["channels"][0]["evidence_quote"] == "«cannes»"
        assert out["adjacent_terms"] == [{"term": "young lions", "channels": [1]}]
