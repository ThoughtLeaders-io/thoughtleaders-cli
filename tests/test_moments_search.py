import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/tl-brand-creator-connection/scripts"))
import moments_search as ms  # noqa: E402

DOCS = json.loads((ROOT / "tests/fixtures/moments_search_docs.json").read_text())


def fake(monkeypatch, spans=None, sponsors=None):
    calls = []

    def tl_json(args, input_text=None, timeout=None):
        body = json.loads(input_text)
        calls.append(body)
        older = any("lt" in f.get("range", {}).get("publication_date", {})
                    for f in body["query"]["bool"]["filter"])
        return {"results": [] if older else [{k: v for k, v in d.items() if k != "transcript"} for d in DOCS]}

    def db_es(body):
        if "transcript" in body["_source"]:
            calls.append({"transcripts": body["query"]["ids"]["values"]})
            return [{"id": d["_id"], "transcript": d["transcript"]}
                    for d in DOCS if d["_id"] in body["query"]["ids"]["values"]]
        rows = []
        for ref in body["query"]["ids"]["values"]:
            ms_ = [{"type": "sponsored", "field": "transcript", "id": b, "start_ts": s, "end_ts": e}
                   for b, s, e in (spans or {}).get(ref, [])]
            ms_ += [{"type": "sponsored", "field": "description", "id": b} for b in (sponsors or {}).get(ref, [])]
            rows.append({"id": ref, "brand_mentions": ms_})
        return rows

    monkeypatch.setattr(ms.tl_data, "_tl_json", tl_json)
    monkeypatch.setattr(ms.tl_data, "_require_complete", lambda d: None)
    monkeypatch.setattr(ms.tl_data, "db_es", db_es)
    return calls


def test_windows_come_from_phrase_hits_with_plurals_and_links(monkeypatch):
    fake(monkeypatch)
    out = ms.run(77, [9], {"occasions": [{"occasion": "travel", "phrases": ["airport", "hotel", "holiday"]}]},
                 "2026-11-16")
    ups = {u["video_id"]: u for u in out["occasions"][0]["uploads_with_windows"]}
    starts = [w["start"] for w in ups["vidA"]["windows"]]
    assert starts == [0, 120]                      # the first cue from 10 s before each hit, 45 s apart
    assert "I'm so tired" in ups["vidA"]["windows"][1]["text"]   # entities unescaped twice
    assert ups["vidB"]["windows"][0]["hit"].lower() == "holidays"
    assert out["queries"] == 1


def test_an_upload_two_searches_find_is_downloaded_once(monkeypatch):
    calls = fake(monkeypatch)
    plan = {"occasions": [{"occasion": "travel", "phrases": ["airport"]},
                          {"occasion": "rest", "phrases": ["hotel"]}]}
    ms.run(77, [9], plan, "2026-11-16")
    fetched = [r for c in calls if "transcripts" in c for r in c["transcripts"]]
    assert sorted(fetched) == ["77:vidA", "77:vidB"]
    assert not any("transcript" in c.get("_source", []) for c in calls if "query" in c)


def test_mechanical_drops_and_flags(monkeypatch):
    fake(monkeypatch, spans={"77:vidB": [(9, 0, 15)]}, sponsors={"77:vidA": [9]})
    out = ms.run(77, [9], {"occasions": [{"occasion": "shop", "phrases": ["checkout", "holiday"]}],
                           "brand_terms": ["wifi"]}, "2026-11-16")
    shop = out["occasions"][0]
    assert all(u["video_id"] != "vidB" for u in shop["uploads_with_windows"])   # within 60 s of a read
    assert out["dropped_near_sponsored_read"] >= 1
    assert out["brand_uploads"] == []              # the brand sponsored vidA: not a brand moment
    assert out["dropped_brand_sponsored_uploads"] == 1


def test_the_budget_and_the_older_search(monkeypatch):
    calls = fake(monkeypatch)
    plan = {"occasions": [{"occasion": "none", "phrases": ["skydiving"]}]}
    out = ms.run(77, [9], plan, "2026-11-16")
    assert out["queries"] == 2                     # recent found nothing, so one older search
    assert out["occasions"][0]["recent"] is False
    many = {"occasions": [{"occasion": f"o{i}", "phrases": ["airport"]} for i in range(20)]}
    out = ms.run(77, [9], many, "2026-11-16", max_queries=16)
    assert out["queries"] == 16 and len(out["budget_skipped_occasions"]) == 4
    assert all(c["size"] <= 20 for c in calls if "size" in c)


CANDS = {"queries": 5, "terms": {"airport": 3}, "budget_skipped_occasions": [],
         "dropped_near_sponsored_read": 2, "dropped_brand_sponsored_uploads": 1,
         "occasions": [{"occasion": "travel", "recent": False, "uploads_with_windows": [
             {"video_id": "v1", "title": "Trip", "published": "2025-03-01", "views": 10,
              "windows": [{"start": 963, "text": "ok  so we got to the airport and I turned my VPN on right away"}]}]}],
         "brand_uploads": [{"video_id": "v2", "title": "Haul", "published": "2026-01-02", "views": 5,
                            "windows": [{"start": 120, "text": "I use Tunnelo on my phone"}]}]}


def test_pick_copies_exact_text_and_cuts_a_stretch():
    probe, missing = ms.pick(CANDS, {"windows": [{"video_id": "v1", "start": 963, "occasion": "travel",
                                                  "from": "so we got", "to": "my vpn on"}],
                                     "brand_windows": [{"video_id": "v2", "start": 120}], "note": "fine"})
    assert missing == []
    w = probe["windows"][0]
    assert w["text"] == "so we got to the airport and I turned my VPN on"
    assert w["url"] == "https://www.youtube.com/watch?v=v1&t=963s" and w["occasion"] == "travel"
    assert probe["brand_windows"][0]["text"] == "I use Tunnelo on my phone"
    assert "occasion" not in probe["brand_windows"][0]
    assert probe["terms"] == {"airport": 3}
    note = probe["coverage"]["note"]
    assert note.startswith("fine") and "5 searches" in note and "older uploads searched for: travel" in note


def test_pick_reports_what_it_cannot_find_and_never_guesses():
    probe, missing = ms.pick(CANDS, {"windows": [{"video_id": "v1", "start": 963, "from": "not said"},
                                                 {"video_id": "v9", "start": 1}]})
    assert probe["windows"] == []
    assert missing == ["v1@963", "v9@1 (no such window)"]


def test_pick_with_no_candidates_writes_empty_lists():
    probe, missing = ms.pick({}, {"note": "search failed: timeout"})
    assert probe["windows"] == [] and probe["brand_windows"] == [] and missing == []
    assert "search failed" in probe["coverage"]["note"]


def test_render_text_keeps_every_window_whole():
    import moments_search as ms
    long = "I always turn my security on at the airport " * 12
    out = {"queries": 3, "brand_windows_total": 1,
           "occasions": [{"occasion": "travel", "recent": True, "windows_total": 2,
                          "uploads_with_windows": [{"video_id": "v1", "title": "Trip", "published": "2026-01-02",
                                                    "views": 10, "windows": [{"start": 5, "text": long, "first_person": True},
                                                                             {"start": 90, "text": "hotel wifi again"}]}]}],
           "brand_uploads": [{"video_id": "v2", "title": "Haul", "published": "2025-05-05", "views": 3,
                              "windows": [{"start": 12, "text": "my tunnelo is on"}]}]}
    txt = ms.render_text(out)
    assert ms._norm(long) in txt
    assert "[v1 5] first_person | " in txt and "[v1 90]  | hotel wifi again" in txt
    assert "=== BRAND NAMED (1 windows)" in txt and "[v2 12]" in txt


def test_the_cap_keeps_first_person_then_newest(monkeypatch):
    fake(monkeypatch)
    plan = {"occasions": [{"occasion": "travel", "phrases": ["airport", "hotel", "holiday"]}]}
    every = [dict(w, video_id=u["video_id"], published=u["published"])
             for u in ms.run(77, [9], plan, "2026-11-16")["occasions"][0]["uploads_with_windows"]
             for w in u["windows"]]
    monkeypatch.setattr(ms, "PER_OCCASION", 1)
    occ = ms.run(77, [9], plan, "2026-11-16")["occasions"][0]
    kept = occ["uploads_with_windows"][0]
    first_person = [w for w in every if w.get("first_person")]
    pool = first_person or every
    newest = max(w["published"] for w in pool)
    assert occ["windows_total"] == 1
    assert kept["published"] == newest
    assert bool(kept["windows"][0].get("first_person")) == bool(first_person)
