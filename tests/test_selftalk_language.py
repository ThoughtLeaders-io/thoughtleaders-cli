"""Language behaviour of the creator-brief recall pass.

The English recall lexicons must gate only English-language videos; other
languages keep every window for the multilingual model layer (pro-drop
Spanish has no pronoun for an English-shaped regex to find). Run as a
subprocess against a stub `tl` binary, like the shared-wrapper tests.
"""

import json
import stat
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "tl-creator-brief" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "_shared"))
import selftalk_scan  # noqa: E402


def _stub_tl(tmp_path: Path) -> Path:
    """A fake `tl` whose every query returns zero rows (no sponsor spans)."""
    script = tmp_path / "tl-stub.py"
    script.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "sys.stdin.read()\nprint('{\"results\": []}')\n"
    )
    runner = tmp_path / "tl"
    runner.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    runner.chmod(runner.stat().st_mode | stat.S_IEXEC)
    return runner


def _run_scan(tmp_path: Path, videos: list[dict]) -> tuple[dict, list[dict]]:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(v) for v in videos) + "\n")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "selftalk_scan.py"),
         "--corpus", str(corpus)],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "TL_CLI_BIN": str(_stub_tl(tmp_path))},
    )
    summary = json.loads(proc.stdout)
    windows = [json.loads(line) for line in
               (tmp_path / "windows.jsonl").read_text().splitlines()]
    return summary, windows


def test_non_english_windows_bypass_the_english_lexicon_gate(tmp_path):
    summary, windows = _run_scan(tmp_path, [
        # Pro-drop Spanish self-disclosure: zero English first-person tokens.
        {"id": "1:aaa", "title": "Mi historia", "transcript_language": "es",
         "publication_date": "2026-01-01",
         "cues": [[5, "crecí en madrid con toda la familia y estudié derecho"]]},
        # English with no first-person signal: the gate must still drop it.
        {"id": "1:bbb", "title": "Weather", "transcript_language": "en",
         "publication_date": "2026-01-02",
         "cues": [[3, "the weather is nice today and the market went up"]]},
        # English self-disclosure: kept and lexicon-ranked.
        {"id": "1:ccc", "title": "My story", "transcript_language": "en",
         "publication_date": "2026-01-03",
         "cues": [[7, "i grew up in ohio and my dad ran a bakery"]]},
    ])
    langs = {w["language"] for w in windows}
    assert "es" in langs and "en" in langs
    assert not any(w["video_id"] == "bbb" for w in windows)
    assert summary["dropped_no_first_person_no_entity"] == 1
    assert summary["non_english_windows_kept"] == 1
    assert summary["languages"] == {"es": 1, "en": 2}
    # The English gem carries lexicon features; the Spanish window is simply
    # kept, unranked, for the model layer.
    en = next(w for w in windows if w["video_id"] == "ccc")
    assert en["cues_fired"]
    es = next(w for w in windows if w["video_id"] == "aaa")
    assert es["language"] == "es"


def test_lexicon_on_forces_the_english_gate_everywhere(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps(
        {"id": "1:aaa", "title": "Mi historia", "transcript_language": "es",
         "publication_date": "2026-01-01",
         "cues": [[5, "crecí en madrid con toda la familia"]]}) + "\n")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "selftalk_scan.py"),
         "--corpus", str(corpus), "--lexicon", "on"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "TL_CLI_BIN": str(_stub_tl(tmp_path))},
    )
    summary = json.loads(proc.stdout)
    assert summary["windows_kept"] == 0
    assert summary["dropped_no_first_person_no_entity"] == 1


def test_tokenization_is_unicode_aware():
    assert "josé" in selftalk_scan._window_tokens("Hola, soy José")
    assert "日本" in selftalk_scan._window_tokens("私は日本に住んでいます 日本")
    hits = selftalk_scan.FuzzyMatcher(["José García"]).hits(
        selftalk_scan._window_tokens("con josé garcía en el estudio"))
    assert hits and hits[0][1] == "strong"


def test_max_windows_caps_batches_but_not_the_recall_record(tmp_path):
    # 8 ranked English disclosure windows + 12 unranked Spanish ones,
    # capped at 5: proportional split, ranked keep top scores, unranked
    # stride-sampled across the catalogue instead of truncated at one end.
    videos = [
        {"id": f"1:en{i:02d}", "title": "My story", "transcript_language": "en",
         "publication_date": f"2026-01-{i + 1:02d}",
         "cues": [[7, "i grew up in ohio and my dad ran a bakery"]]}
        for i in range(8)
    ] + [
        # ids run OPPOSITE to publication order: sampling must follow dates,
        # not the arbitrary video-id sort.
        {"id": f"1:es{11 - i:02d}", "title": "Historia",
         "transcript_language": "es",
         "publication_date": f"2026-02-{i + 1:02d}",
         "cues": [[5, "crecí en madrid con toda la familia y estudié derecho"]]}
        for i in range(12)
    ]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(v) for v in videos) + "\n")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "selftalk_scan.py"),
         "--corpus", str(corpus), "--max-windows", "5"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "TL_CLI_BIN": str(_stub_tl(tmp_path))},
    )
    summary = json.loads(proc.stdout)
    assert summary["windows_kept"] == 20
    assert summary["windows_batched"] == 5
    assert summary["windows_over_cap"] == 15
    # The full recall record stays intact for free local re-scans.
    record = (tmp_path / "windows.jsonl").read_text().splitlines()
    assert len(record) == 20
    batched = [w for p in summary["batches"]
               for w in json.loads(Path(p).read_text())]
    assert len(batched) == 5
    es_dates = sorted(w["published"] for w in batched
                      if w["language"] == "es")
    en_ids = [w["video_id"] for w in batched if w["language"] == "en"]
    assert en_ids and es_dates
    # Stride sampling spans the channel's HISTORY (publication dates), not
    # one end of it — and not the arbitrary video-id order.
    assert es_dates[0] <= "2026-02-02" and es_dates[-1] >= "2026-02-08"


def test_max_windows_zero_disables_the_cap(tmp_path):
    videos = [
        {"id": f"1:v{i:02d}", "title": "My story", "transcript_language": "en",
         "publication_date": "2026-01-01",
         "cues": [[7, "i grew up in ohio and my dad ran a bakery"]]}
        for i in range(4)
    ]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(v) for v in videos) + "\n")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "selftalk_scan.py"),
         "--corpus", str(corpus), "--max-windows", "0"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "TL_CLI_BIN": str(_stub_tl(tmp_path))},
    )
    summary = json.loads(proc.stdout)
    assert summary["windows_batched"] == summary["windows_kept"] == 4
    assert summary["windows_over_cap"] == 0
