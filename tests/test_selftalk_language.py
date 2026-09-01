"""Language behaviour of the creator-brief recall pass.

The English recall lexicons must gate only English-language videos; other
languages keep every window for the multilingual model layer (pro-drop
Spanish has no pronoun for an English-shaped regex to find). Run as a
subprocess against a stub `tl` binary, like the shared-wrapper tests.
"""

import gzip
import json
import re
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
    return summary, _windows(tmp_path)


def _windows(out_dir: Path) -> list[dict]:
    """The recall record, read back out of the gzipped windows file."""
    with gzip.open(out_dir / "windows.jsonl.gz", "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


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
    assert len(_windows(tmp_path)) == 20
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


def test_zero_score_english_windows_never_displace_ranked_ones(tmp_path):
    # 6 high-signal English windows + 20 first-person-only English windows
    # (rank_score 0). The zero-score windows are RANKED (low), not
    # "unranked": with a cap of 6 the stride pool must stay empty and every
    # slot must go to the disclosure windows, not to stride-sampled noise.
    videos = [
        {"id": f"1:hi{i:02d}", "title": "My story", "transcript_language": "en",
         "publication_date": f"2026-01-{i + 1:02d}",
         "cues": [[7, "i grew up in ohio and my dad ran a bakery"]]}
        for i in range(6)
    ] + [
        {"id": f"1:lo{i:02d}", "title": "Gameplay", "transcript_language": "en",
         "publication_date": f"2026-02-{i + 1:02d}",
         "cues": [[3, "i think we should attack the boss now come on"]]}
        for i in range(20)
    ]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(v) for v in videos) + "\n")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "selftalk_scan.py"),
         "--corpus", str(corpus), "--max-windows", "6"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "TL_CLI_BIN": str(_stub_tl(tmp_path))},
    )
    summary = json.loads(proc.stdout)
    batched = [w for p in summary["batches"]
               for w in json.loads(Path(p).read_text())]
    assert [w["video_id"] for w in batched] == [f"hi{i:02d}" for i in range(6)]


# --------------------------------------------------------------------------- #
# performance rework: the fast paths must not move a single output byte
# --------------------------------------------------------------------------- #
def _scan_with_workers(tmp_path: Path, corpus: Path, workers: str,
                       out: Path, env: dict | None = None
                       ) -> tuple[dict, list[dict]]:
    out.mkdir(exist_ok=True)
    target = out / "corpus.jsonl"
    target.write_text(corpus.read_text())
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "selftalk_scan.py"),
         "--corpus", str(target), "--host-terms", "Patterrz,Social Chain"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "TL_CLI_BIN": str(_stub_tl(tmp_path)),
             "CREATOR_BRIEF_SCAN_WORKERS": workers,
             **(env or {})},
    )
    return json.loads(proc.stdout), _windows(out)


def test_worker_pool_and_serial_path_agree_window_for_window(tmp_path):
    """The multiprocessing scan splits by video and merges in submission
    order, so it must reproduce the serial kept-window list exactly — same
    windows, same field values, same order. A worker that saw a different
    slice of the corpus, or a merge that reordered chunks, shows up here.
    No hash seed is pinned: the output must be stable on its own.

    The chunk floor is lowered through the environment so this 40-video
    fixture really is split across processes — at the production floor it
    would be one chunk and both runs would take the serial path, comparing
    nothing. `parallel_chunks` in each summary says which path actually ran,
    so the test fails loudly if the pool is ever skipped again."""
    corpus = tmp_path / "src.jsonl"
    videos = []
    for i in range(40):
        videos.append({
            "id": f"1:vid{i:03d}",
            "title": "My story" if i % 3 else "Interview with a guest",
            "transcript_language": "en" if i % 7 else "es",
            "publication_date": f"2026-01-{(i % 28) + 1:02d}",
            "cues": [
                [10 + j * 7,
                 f"i grew up in ohio and my dad ran a bakery number {j} "
                 f"and patterrz said remember to subscribe to my channel "
                 f"while i was working at social chain in video {i}"]
                for j in range(6)
            ],
        })
    corpus.write_text("".join(json.dumps(v) + "\n" for v in videos))

    small_chunks = {"CREATOR_BRIEF_SCAN_MIN_CHUNK": "10"}
    serial_summary, serial = _scan_with_workers(
        tmp_path, corpus, "1", tmp_path / "serial", small_chunks)
    parallel_summary, parallel = _scan_with_workers(
        tmp_path, corpus, "2", tmp_path / "parallel", small_chunks)

    # the paths under comparison are really the two different paths
    assert serial_summary["parallel_chunks"] == 0
    assert parallel_summary["parallel_chunks"] == 4

    assert serial, "the fixture produced no kept windows to compare"
    assert parallel == serial
    for key, value in serial_summary.items():
        if key in ("elapsed_s", "corpus", "windows_file", "batches",
                   "parallel_chunks"):
            continue
        assert parallel_summary[key] == value, key


def test_lexicons_read_the_same_as_case_insensitive_matching():
    """The lexicons are matched against pre-lower-cased text instead of
    carrying re.IGNORECASE. That is only sound while every pattern is
    all-lower-case ASCII, so assert the equivalence directly."""
    samples = [
        "I Grew Up In Ohio And MY DAD ran a bakery",
        "SUBSCRIBE and smash that like, link in the description",
        "In This Video I'm Going To Show you my channel",
        "I CONSIDER MYSELF a big fan of My Favourite Show",
        "Personally I moved to Berlin when I was 9 and got fired",
        "nothing here at all, just weather and markets",
        "MI FAMILIA Y YO CRECIMOS EN MADRID",
        "私は日本に住んでいます I'm From Tokyo",
    ]
    patterns = [selftalk_scan.FIRST_PERSON, selftalk_scan.WEAK_ANCHOR,
                selftalk_scan.STAGE, selftalk_scan.BOILERPLATE,
                selftalk_scan.BOILER_FP]
    patterns += [rx for _, rx in selftalk_scan.DISCLOSURE]
    for rx in patterns:
        assert not rx.flags & re.IGNORECASE, rx.pattern[:40]
        insensitive = re.compile(rx.pattern, re.I)
        for text in samples:
            assert bool(rx.search(text.lower())) == \
                bool(insensitive.search(text)), (rx.pattern[:40], text)


def test_windows_carry_no_assembled_url(tmp_path):
    """A window stores video_id + start; the watch URL is derived wherever a
    window is shown, never written half a million times to disk."""
    _, windows = _run_scan(tmp_path, [
        {"id": "1:ccc", "title": "My story", "transcript_language": "en",
         "publication_date": "2026-01-03",
         "cues": [[7, "i grew up in ohio and my dad ran a bakery"]]},
    ])
    assert windows and all("url" not in w for w in windows)
    w = windows[0]
    assert (f"https://www.youtube.com/watch?v={w['video_id']}"
            f"&t={w['start']}s") == "https://www.youtube.com/watch?v=ccc&t=7s"


def test_recurring_phrase_does_not_depend_on_the_hash_seed(tmp_path):
    """Several phrases can recur in exactly as many videos. The winner is the
    lexicographically smallest, not whichever the phrase SET yielded first —
    which used to make the same corpus scan two different ways."""
    corpus = tmp_path / "src.jsonl"
    # Three uploads repeat one distinctive sentence: every 4-gram in it
    # recurs in exactly the same three videos, so they all tie on the count
    # the winner is picked by. Seven filler uploads keep those words rare.
    videos = [
        {"id": f"1:rep{i:02d}", "title": "My story",
         "transcript_language": "en",
         "publication_date": f"2026-01-{i + 1:02d}",
         "cues": [[10, "i grew up hunting zebra quartz beside vermilion "
                       "obelisk juniper and my dad ran a bakery"]]}
        for i in range(3)
    ] + [
        {"id": f"1:fil{i:02d}", "title": "My story",
         "transcript_language": "en",
         "publication_date": f"2026-02-{i + 1:02d}",
         "cues": [[10, "i moved to ohio and my dad ran a bakery there"]]}
        for i in range(7)
    ]
    corpus.write_text("".join(json.dumps(v) + "\n" for v in videos))

    runs = [_scan_with_workers(tmp_path, corpus, "1", tmp_path / f"seed{seed}",
                               {"PYTHONHASHSEED": seed})[1]
            for seed in ("0", "1", "12345")]
    phrases = {tuple(w["recurring_phrase"] for w in run) for run in runs}
    assert len(phrases) == 1, phrases
    assert runs[0] == runs[1] == runs[2]
    assert any(w["recurring_phrase"] for w in runs[0]), "no phrase recurred"
