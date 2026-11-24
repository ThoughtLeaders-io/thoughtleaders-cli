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


PET = {**FACT, "fact_id": "p1", "domain": "pets", "claim": "walks their dog Luna every morning",
       "people": [{"name": "Luna", "relation": "dog"}]}


@pytest.mark.parametrize("people", [
    [{"name": "Luna", "relation": "dog"}], [{"name": "Luna", "relation": None}],
    [{"name": "Luna", "relation": "rescue dog"}],
    [{"name": "Luna", "relation": "cat"}, {"name": "Milo", "relation": "kitten"}],
])
def test_named_pets_reach_the_gift_with_their_names(people):
    result = gifts.candidates(META, [{**PET, "people": people}], 42, TODAY, "host")
    assert [c["fact_id"] for c in result["candidates"]] == ["p1"]
    assert result["candidates"][0]["pet_names"] == [p["name"] for p in people]


def test_unnamed_pet_type_reaches_the_gift_without_names():
    result = gifts.candidates(META, [{**PET, "claim": "has a cat", "people": []}], 42, TODAY, "host")
    assert [c["fact_id"] for c in result["candidates"]] == ["p1"]
    assert "pet_names" not in result["candidates"][0]


@pytest.mark.parametrize("changes", [
    {"people": [{"name": "PRIVATE NAME", "relation": "wife"}]},
    {"people": [{"name": "Luna", "relation": "dog"}, {"name": "PRIVATE NAME", "relation": "friend"}]},
    {"people": [{"name": "PRIVATE NAME", "relation": "bandmate"}]},
    {"domain": "habits", "people": [{"name": "PRIVATE NAME", "relation": None}]},
    {"domain": "habits", "people": [{"name": "PRIVATE NAME", "relation": "dog"}]},
    {"people": [{"name": "", "relation": "dog"}]}, {"people": "PRIVATE NAME"},
    {"people": [{"name": "Luna", "relation": "dog", "of": "PRIVATE OWNER"}]},
    {"people": [{"name": "PRIVATE NAME", "relation": None}, {"name": "Luna", "relation": "dog"}]},
    {"claim": "walks PRIVATE NAME every morning", "people": [{"name": "PRIVATE NAME", "relation": None}]},
    {"ended": True}, {"last_seen": "2024-01-01"},
])
def test_pet_facts_naming_a_person_or_no_longer_current_never_appear(changes):
    fact = {**PET, "claim": "PRIVATE REJECTED DETAIL", **changes}
    result = gifts.candidates(META, [fact], 42, TODAY, "host")
    assert result["candidates"] == []
    assert "PRIVATE" not in json.dumps(result)


def test_finds_brand_creator_connection_installed_beside_it(tmp_path):
    skills = tmp_path / "skills"
    shutil.copytree(ROOT / "skills/tl-creator-gifts", skills / "tl-creator-gifts")
    shutil.copytree(ROOT / "skills/tl-brand-creator-connection", skills / "tl-brand-creator-connection")
    ledger = tmp_path / "42-facts.jsonl"
    ledger.write_text("\n".join(json.dumps(x) for x in (META, FACT, PET)))
    command = [sys.executable, str(skills / "tl-creator-gifts/scripts/gift_candidates.py"),
               "--ledger", str(ledger), "--channel", "42",
               "--as-of", TODAY.isoformat(), "--recipient-role", "host"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert [c["fact_id"] for c in out["candidates"]] == ["f1", "p1"]
    assert out["candidates"][1]["pet_names"] == ["Luna"]
    shutil.rmtree(skills / "tl-brand-creator-connection")
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert "tl-brand-creator-connection was not found" in result.stderr


@pytest.mark.parametrize("missing", ["speaker", "last_seen"])
def test_ledger_from_before_the_speaker_fields_asks_for_a_rebuild(missing):
    old = {k: v for k, v in FACT.items() if k != missing}
    with pytest.raises(gifts.RebuildRequired):
        gifts.candidates(META, [FACT, {**old, "fact_id": "f2"}], 42, TODAY, "host")


def test_web_fact_without_speaker_is_the_hosts_on_a_one_host_channel():
    web = {**FACT, "fact_id": "w1", "provenance": "web", "source_url": "https://example.com/a"}
    del web["speaker"], web["last_seen"]
    web["seen_date"] = "2026-09-01"
    result = gifts.candidates(META, [web], 42, TODAY, "host")
    assert [(c["fact_id"], c["speaker"]) for c in result["candidates"]] == [("w1", "host")]
    multi = gifts.candidates({**META, "format": "multi_host"}, [web], 42, TODAY, "host")
    assert multi["candidates"] == [] and multi["rejected_counts"] == {"recipient_mismatch": 1}


def test_old_ledger_reports_rebuild_not_no_good_fit(tmp_path):
    old = {k: v for k, v in FACT.items() if k not in ("speaker", "last_seen")}
    ledger = tmp_path / "42-facts.jsonl"
    ledger.write_text("\n".join(json.dumps(x) for x in (META, old)))
    command = [sys.executable, str(SCRIPT), "--ledger", str(ledger), "--channel", "42",
               "--as-of", TODAY.isoformat(), "--recipient-role", "host"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    out = json.loads(result.stdout)
    assert out["status"] == "profile_rebuild_needed"
    assert "--rebuild" in out["reason"]


OLD = {**FACT, "last_seen": "2022-04-07", "published": "2022-04-07"}


@pytest.mark.parametrize("claim,why", [
    ("toffee crunch is one of her favorite chocolates", "stated_as_lasting"),
    ("Loves a good maxi skirt", "stated_as_lasting"),
    ("still wears clogs and probably always will", "stated_as_lasting"),
])
def test_older_favourites_come_back_as_lasting(claim, why):
    result = gifts.candidates(META, [{**OLD, "claim": claim}], 42, TODAY, "host")
    assert result["candidates"] == []
    assert [(c["claim"], c["lasting"]) for c in result["lasting_favourites"]] == [(claim, why)]
    assert "review" in result["status"]


def test_older_fact_repeated_across_years_is_lasting():
    fact = {**OLD, "claim": "collects fancy soaps", "published": "2019-05-01",
            "last_seen": "2023-08-29", "recurrence": 3}
    assert gifts.candidates(META, [fact], 42, TODAY, "host")["lasting_favourites"][0]["lasting"] == \
        "repeated_across_years"


@pytest.mark.parametrize("changes", [
    {"claim": "keeps a paper walking journal"},
    {"claim": "as of this video, loved white trainers"},
    {"claim": "used to love running"},
    {"claim": "came out of Love Lane with lots of clothes"},
    {"claim": "loves walking their dog Luna", "domain": "pets", "people": [{"name": "Luna", "relation": "dog"}]},
    {"claim": "PRIVATE always loves it", "sensitivity": "clinical"},
    {"claim": "PRIVATE always loves it", "speaker": "cohost"},
    {"claim": "PRIVATE always loves it", "last_seen": "2099-01-01"},
])
def test_older_facts_that_are_not_lasting_stay_out(changes):
    result = gifts.candidates(META, [{**OLD, **changes}], 42, TODAY, "host")
    assert result["candidates"] == [] and result["lasting_favourites"] == []
    assert "PRIVATE" not in json.dumps(result)


def test_lasting_list_is_capped_with_repeated_facts_first():
    facts = [{**OLD, "fact_id": f"f{i}", "claim": "loves stickers"} for i in range(20)]
    facts.append({**OLD, "fact_id": "r1", "claim": "collects soaps", "published": "2019-01-01",
                  "last_seen": "2021-01-01", "recurrence": 2})
    result = gifts.candidates(META, facts, 42, TODAY, "host")
    assert len(result["lasting_favourites"]) == gifts.LASTING_LIMIT
    assert result["lasting_favourites"][0]["fact_id"] == "r1"
    assert result["rejected_counts"]["stale_or_undated"] == 21 - gifts.LASTING_LIMIT


FAN = {**FACT, "fact_id": "a1", "domain": "tastes", "claim": "reads every novel by Ingrid Solvang"}


@pytest.mark.parametrize("people", [
    [{"name": "Ingrid Solvang", "relation": "favourite author"}],
    [{"name": "Marco Bellweather", "relation": "actor"}],
    [{"name": "The Lanterns", "relation": "favorite band"}],
    [{"name": "Ada Quill", "relation": "painter"}, {"name": "Ben Ostry", "relation": "illustrator"}],
])
def test_public_figures_reach_the_gift_with_their_names(people):
    result = gifts.candidates(META, [{**FAN, "people": people}], 42, TODAY, "host")
    assert [c["fact_id"] for c in result["candidates"]] == ["a1"]
    assert result["candidates"][0]["public_figures"] == [p["name"] for p in people]
    assert "pet_names" not in result["candidates"][0]


@pytest.mark.parametrize("changes", [
    {"people": [{"name": "PRIVATE NAME", "relation": "artist friend"}]},
    {"people": [{"name": "PRIVATE NAME", "relation": "sister, an actress"}]},
    {"people": [{"name": "PRIVATE NAME", "relation": "wife's favourite author"}]},
    {"people": [{"name": "PRIVATE NAME", "relation": None}]},
    {"people": [{"name": "PRIVATE NAME", "relation": "hero"}]},
    {"people": [{"name": "PRIVATE NAME", "relation": "favourite author", "of": "PRIVATE FRIEND"}]},
    {"people": [{"name": "Ingrid Solvang", "relation": "author"}, {"name": "PRIVATE NAME", "relation": "friend"}]},
    {"domain": "family", "people": [{"name": "PRIVATE NAME", "relation": "actor"}]},
    {"domain": "pets", "people": [{"name": "PRIVATE NAME", "relation": "author"}]},
])
def test_private_people_never_pass_as_public_figures(changes):
    result = gifts.candidates(META, [{**FAN, **changes}], 42, TODAY, "host")
    assert result["candidates"] == []
    assert not result.get("lasting_favourites")
    assert "PRIVATE" not in json.dumps(result)


def test_a_host_gift_never_carries_the_cohosts_pet():
    meta = {**META, "format": "multi_host", "hosts": {"host": "Ana", "cohost": "Ben"}}
    fact = {**PET, "claim": "PRIVATE Ben has a dog named Rex",
            "people": [{"name": "Rex", "relation": "dog", "of": "Ben"}]}
    result = gifts.candidates(meta, [fact], 42, TODAY, "host")
    assert result["candidates"] == []
    assert "PRIVATE" not in json.dumps(result)


def test_unrelated_name_is_a_pet_only_when_the_claim_says_so():
    fact = {**PET, "claim": "adopted a rescue dog named Luna", "people": [{"name": "Luna", "relation": None}]}
    result = gifts.candidates(META, [fact], 42, TODAY, "host")
    assert result["candidates"][0]["pet_names"] == ["Luna"]
