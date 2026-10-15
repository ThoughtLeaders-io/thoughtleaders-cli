"""Gift consumers must abstain on unsafe evidence and work outside the repo."""
import copy
import datetime as dt
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/tl-creator-gifts/scripts/gift_candidates.py"
SPEC = importlib.util.spec_from_file_location("gift_candidates", SCRIPT)
gifts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gifts)
TODAY = dt.date(2026, 10, 16)
META = {"schema": "tl-creator-meta/v2", "channel_id": 42,
        "generated_at": "2026-10-15", "format": "solo"}
FACT = {"fact_id": "f1", "claim": "keeps a paper walking journal",
        "domain": "habits", "confidence": "confirmed", "sensitivity": "none",
        "sensitive": False, "speaker": "host", "people": [],
        "last_seen": "2026-09-01", "provenance": "transcript",
        "quote": "I always keep a paper walking journal", "video": "42:abcdef",
        "start": 123.0, "url": "https://www.youtube.com/watch?v=abcdef&t=123s"}


def test_published_exact_writer_output_needs_no_stripped_verify_field():
    result = gifts.candidates(META, [FACT], 42, TODAY, "host")
    assert result["candidates"][0]["fact_id"] == "f1"
    assert "review" in result["status"]


@pytest.mark.parametrize("changes", [
    {"confidence": "unconfirmed"}, {"ended": True}, {"superseded_by": "f2"},
    {"staged_only": True}, {"hook_only": True}, {"unverified_bio": True},
    {"sensitivity": "clinical"}, {"sensitivity": "children"},
    {"sensitivity": "location"}, {"sensitivity": None}, {"sensitive": None},
    {"domain": "relationships"}, {"domain": "money"},
    {"people": [{"name": "PRIVATE NAME", "relation": "spouse"}]},
    {"speaker": "cohost"}, {"speaker": "shared"}, {"speaker": "guest"},
    {"last_seen": "2024-10-15"}, {"last_seen": "2099-01-01"},
    {"last_seen": "unknown"}, {"url": "javascript:private"},
    {"last_seen": "2026-09-01gibberish"}, {"published": "2027-01-01"},
    {"url": "https://127.0.0.1/private"}, {"video": "99:abcdef"},
    {"url": "https://www.youtube.com/watch?v=wrong-video"},
    {"quote": ""}, {"start": -1}, {"start": True}, {"start": float("nan")},
    {"verify": {"match": "partial"}}, {"verify": None},
    {"provenance": "mystery"}, {"fact_id": ""},
])
def test_rejected_premises_never_appear_in_output(changes):
    fact = {**FACT, "claim": "PRIVATE REJECTED DETAIL", **changes}
    result = gifts.candidates(META, [fact], 42, TODAY, "host")
    assert result["candidates"] == []
    assert "PRIVATE" not in json.dumps(result)


def test_superseded_and_unconfirmed_contradictions_do_not_win():
    facts = [{**FACT, "superseded_by": "f2"},
             {**FACT, "fact_id": "f2", "confidence": "unconfirmed"}]
    assert gifts.candidates(META, facts, 42, TODAY, "host")["candidates"] == []


def test_multi_host_role_does_not_use_named_people_as_recipient():
    meta = {**META, "format": "multi_host"}
    facts = [FACT, {**FACT, "fact_id": "f2", "speaker": "cohost"}]
    assert [f["fact_id"] for f in gifts.candidates(meta, facts, 42, TODAY, "cohost")["candidates"]] == ["f2"]


@pytest.mark.parametrize("meta", [None, {**META, "channel_id": 99},
    {**META, "schema": "tl-creator-meta/v99"}, {**META, "generated_at": "2025-01-01"},
    {**META, "generated_at": "2099-01-01"}, {**META, "format": None}])
def test_bad_profile_requires_profile_pipeline(meta):
    with pytest.raises(ValueError):
        gifts.candidates(meta, [FACT], 42, TODAY, "host")


def test_duplicate_ids_rejected_and_empty_profile_abstains():
    with pytest.raises(ValueError):
        gifts.candidates(META, [FACT, FACT], 42, TODAY, "host")
    assert gifts.candidates(META, [], 42, TODAY, "host")["status"] == "no_eligible_facts"


def test_installed_skills_can_be_unrelated_directories(tmp_path):
    gift_dir = tmp_path / "host-a/gift"
    profile_dir = tmp_path / "host-b/profile"
    shutil.copytree(ROOT / "skills/tl-creator-gifts", gift_dir)
    shutil.copytree(ROOT / "skills/tl-brand-creator-connection", profile_dir)
    ledger = tmp_path / "42-facts.jsonl"
    ledger.write_text("\n".join(json.dumps(x) for x in (META, FACT)))
    command = [sys.executable, str(gift_dir / "scripts/gift_candidates.py"),
               "--profile-skill", str(profile_dir), "--ledger", str(ledger),
               "--channel", "42", "--as-of", TODAY.isoformat(), "--recipient-role", "host"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["candidates"][0]["fact_id"] == "f1"
    ledger.write_text('{"claim": "PRIVATE CONTENT", broken json')
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "PRIVATE" not in result.stdout + result.stderr
    shutil.rmtree(profile_dir)
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0


def test_bio_needs_corroboration():
    fact = copy.deepcopy(FACT)
    fact.update(provenance="bio", source_url="https://example.com/about")
    assert gifts.rejection(fact, TODAY, "host") == "unverified_source"
    fact["corroborated_by"] = ["f2"]
    assert gifts.rejection(fact, TODAY, "host") is None
