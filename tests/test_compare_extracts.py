"""compare_extracts.py: the agreement matrix, quote relations, claim
similarity and the stratified sample, on tiny fixtures. No network."""

import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = (Path(__file__).resolve().parents[1]
            / "skills" / "tl-creator-brief" / "scripts")
sys.path.insert(0, str(_SCRIPTS))
import compare_extracts as ce  # noqa: E402


def _win(n: int) -> dict:
    return {"id": "1:vid", "start": n, "title": "t", "format_hint": None,
            "in_sponsor_read": False,
            "text": f"my dad ran a bakery in a tiny town number {n}"}


def _gem(**kw) -> dict:
    v = {"self_disclosure": True, "speaker_guess": "host",
         "life_domain": "family", "sensitivity": "none",
         "claim": "father ran a bakery in Ohio",
         "quote": "my dad ran a bakery", "confidence": "confirmed"}
    v.update(kw)
    return v


def _not(**kw) -> dict:
    v = {"self_disclosure": False, "speaker_guess": "guest",
         "notable": "third-party"}
    v.update(kw)
    return v


def _side(tmp_path: Path, name: str, verdicts: dict[int, dict]) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "classified.jsonl").write_text("".join(
        json.dumps({"window": _win(n), "verdict": v, "error": None}) + "\n"
        for n, v in verdicts.items()))
    return d


def test_matrix_counts_each_cell_and_the_one_sided_windows(tmp_path):
    a = _side(tmp_path, "a", {1: _gem(), 2: _gem(), 3: _not(), 4: _not(),
                              5: _gem()})
    b = _side(tmp_path, "b", {1: _gem(), 2: _not(), 3: _gem(), 4: _not(),
                              6: _gem()})
    report, _ = ce.compare(ce.load(a), ce.load(b), "agents", "api", 60)
    assert report["matrix"] == {"a_gem_b_gem": 1, "a_gem_b_not": 1,
                                "a_not_b_gem": 1, "a_not_b_not": 1}
    assert report["windows_a"] == 5 and report["windows_b"] == 5
    assert report["windows_both"] == 4
    assert report["judged_by_one_side_only"] == 2      # window 5 and window 6
    assert report["shared_gems"] == 1


def test_shared_gem_agreement_rates_and_speaker_mismatch(tmp_path):
    a = _side(tmp_path, "a", {1: _gem(), 2: _gem(life_domain="pets"),
                              3: _gem()})
    b = _side(tmp_path, "b", {1: _gem(), 2: _gem(),
                              3: _gem(speaker_guess="guest",
                                      sensitivity="clinical")})
    report, sample = ce.compare(ce.load(a), ce.load(b), "x", "y", 60)
    assert report["shared_gems"] == 3
    assert report["speaker_agreement"] == round(2 / 3, 4)
    assert report["domain_agreement"] == round(2 / 3, 4)
    assert report["sensitivity_agreement"] == round(2 / 3, 4)
    # a speaker mismatch on a shared gem is a disagreement for the sample
    assert report["disagreements"] == 1
    assert [e["kind"] for e in sample if e["kind"] == "speaker_mismatch"]


def test_quote_relation_buckets():
    assert ce.quote_bucket("my dad ran a bakery", "My dad ran a bakery!") == \
        "identical"
    assert ce.quote_bucket("my dad ran a bakery in Ohio",
                           "dad ran a bakery") == "contains"
    assert ce.quote_bucket("so my dad ran a bakery",
                           "my dad ran a shop in town") == "overlapping"
    assert ce.quote_bucket("my dad ran a bakery",
                           "we moved to Berlin last year") == "disjoint"
    # three shared words is below the overlap threshold
    assert ce.quote_bucket("my dad ran the store",
                           "my dad ran shops now") == "disjoint"


def test_claim_jaccard_and_its_histogram(tmp_path):
    a = _side(tmp_path, "a", {1: _gem(claim="father ran a bakery"),
                              2: _gem(claim="grew up in Ohio"),
                              3: _gem(claim="owns two cats")})
    b = _side(tmp_path, "b", {1: _gem(claim="father ran a bakery"),
                              2: _gem(claim="grew up in a small town"),
                              3: _gem(claim="rides a motorcycle daily")})
    report, _ = ce.compare(ce.load(a), ce.load(b), "x", "y", 60)
    assert ce.jaccard("father ran a bakery", "Father, ran a bakery!") == 1.0
    assert ce.jaccard("owns two cats", "rides a motorcycle daily") == 0.0
    hist = report["claim_jaccard_histogram"]
    assert hist["0.8-1"] == 1 and hist["0-0.2"] == 1
    assert sum(hist.values()) == 3
    assert 0 < report["claim_jaccard_mean"] < 1


def test_sample_is_all_disagreements_then_strided_agreements(tmp_path):
    # 4 disagreements, 30 agree-gems, 30 agree-not-gems
    av, bv = {}, {}
    for n in range(4):
        av[n], bv[n] = _gem(), _not()
    for n in range(100, 130):
        av[n], bv[n] = _gem(), _gem()
    for n in range(200, 230):
        av[n], bv[n] = _not(), _not()
    a, b = _side(tmp_path, "a", av), _side(tmp_path, "b", bv)
    report, sample = ce.compare(ce.load(a), ce.load(b), "agents", "api",
                                60)
    kinds = [e["kind"] for e in sample]
    assert kinds[:4] == ["a_gem_b_not"] * 4          # disagreements first
    assert kinds.count("agree_gem") == 10
    assert kinds.count("agree_not_gem") == 10
    assert len(sample) == 24 == report["sample_entries"]
    # deterministic even stride over the sorted keys, not the first ten
    starts = [e["start"] for e in sample if e["kind"] == "agree_gem"]
    assert starts == [100, 103, 106, 109, 112, 115, 118, 121, 124, 127]
    # entries carry the window and both sides' whole verdicts
    e = sample[0]
    assert e["video_id"] == "1:vid" and "my dad ran a bakery" in e["text"]
    assert e["title"] == "t" and e["in_sponsor_read"] is False
    assert e["agents"]["self_disclosure"] and not e["api"][
        "self_disclosure"]


def test_sample_size_caps_the_disagreements_too(tmp_path):
    av = {n: _gem() for n in range(20)}
    bv = {n: _not() for n in range(20)}
    a, b = _side(tmp_path, "a", av), _side(tmp_path, "b", bv)
    _, sample = ce.compare(ce.load(a), ce.load(b), "x", "y", 5)
    assert len(sample) == 5 and all(e["kind"] == "a_gem_b_not" for e in sample)


def test_cli_writes_the_report_and_the_sample(tmp_path):
    a = _side(tmp_path, "a", {1: _gem(), 2: _not()})
    b = _side(tmp_path, "b", {1: _gem(), 2: _not()})
    out, sample = tmp_path / "report.json", tmp_path / "sample.json"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "compare_extracts.py"),
         "--a", str(a), "--b", str(b), "--label-a", "agents",
         "--label-b", "api", "--out", str(out), "--sample", str(sample),
         "--sample-size", "30"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text())
    assert json.loads(proc.stdout)["matrix"] == report["matrix"]
    assert report["label_a"] == "agents" and report["label_b"] == "api"
    assert report["matrix"]["a_gem_b_gem"] == 1
    entries = json.loads(sample.read_text())
    assert {e["kind"] for e in entries} == {"agree_gem", "agree_not_gem"}
    assert all("agents" in e and "api" in e for e in entries)


def test_stride_pick_with_nothing_to_pick_is_empty():
    from compare_extracts import stride_pick
    assert stride_pick(["a", "b"], 0) == []
    assert stride_pick([], 3) == []
