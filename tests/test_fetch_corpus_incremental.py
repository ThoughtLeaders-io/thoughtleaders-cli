"""fetch_corpus.py's incremental refetch: the append path, its cursor, the
gzipped store, and the all-or-nothing rename that protects an already-stored
corpus.

No network anywhere: a stub stands in for the `tl` CLI through TL_CLI_BIN (the
seam skills/_shared/tl_data.py resolves), so the script under test runs exactly
as it does in production — argv, stdin body, paging and all.
"""

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[1] / "skills"
_SCRIPTS = _SKILLS / "tl-creator-brief" / "scripts"
_FETCH = _SCRIPTS / "fetch_corpus.py"

sys.path.insert(0, str(_SKILLS / "_shared"))
sys.path.insert(0, str(_SCRIPTS))
import fetch_corpus  # noqa: E402

# Pages a fixture the way ES would: sort by (publication_date, id), honour
# search_after and size, and fail loudly once STUB_FAIL_AFTER calls are spent.
_STUB = '''#!/usr/bin/env python3
import json, os, pathlib, sys

body = json.loads(sys.stdin.read())
counter = pathlib.Path(os.environ["STUB_CALLS"])
n = int(counter.read_text().strip() or "0") + 1
counter.write_text(str(n))
if n > int(os.environ.get("STUB_FAIL_AFTER", "999999")):
    sys.stderr.write("stub: simulated mid-sweep failure\\n")
    sys.exit(3)

rows = json.loads(pathlib.Path(os.environ["STUB_ROWS"]).read_text())
rows.sort(key=lambda r: (r["publication_date"], r["id"]))
after = body.get("search_after")
if after:
    rows = [r for r in rows
            if (r["publication_date"], r["id"]) > (after[0], after[1])]
print(json.dumps({"results": rows[:body.get("size", 500)]}))
'''

CHANNEL = 42


def _doc(i, *, transcript=True):
    return {"id": f"1:vid{i:02d}", "title": f"video {i}",
            "publication_date": f"2024-01-{i:02d}T00:00:00",
            "views": i * 100, "duration": 600, "content_type": "video",
            "transcript": (f'<text start="1.0">hello from video {i}</text>'
                           if transcript else None)}


class Corpus:
    """A scratch corpus root wired to the stub CLI."""

    def __init__(self, tmp: Path):
        self.out = tmp / "corpus-root"
        self.rows = tmp / "rows.json"
        self.calls = tmp / "calls.txt"
        self.calls.write_text("0")
        stub = tmp / "stub_es.py"
        stub.write_text(_STUB)
        self.bin = tmp / "tl"
        self.bin.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}"\n')
        self.bin.chmod(0o755)

    def serve(self, docs):
        """Set what the catalogue currently contains."""
        self.rows.write_text(json.dumps(docs))

    def run(self, *args, fail_after=None):
        env = dict(os.environ)
        env["TL_CLI_BIN"] = str(self.bin)
        env["STUB_ROWS"] = str(self.rows)
        env["STUB_CALLS"] = str(self.calls)
        env["STUB_FAIL_AFTER"] = str(999999 if fail_after is None
                                     else fail_after)
        return subprocess.run(
            [sys.executable, str(_FETCH), "--channel", str(CHANNEL),
             "--out", str(self.out), *args],
            capture_output=True, text=True, env=env)

    def summary(self, *args, **kw):
        proc = self.run(*args, **kw)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout), proc

    @property
    def path(self) -> Path:
        return self.out / str(CHANNEL) / "corpus.jsonl.gz"

    def text(self) -> str:
        """The stored corpus as text — the appended rows of a second gzip
        member included, which is what a reader must see."""
        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            return f.read()

    def ids(self):
        return [json.loads(x)["id"] for x in
                self.text().splitlines() if x.strip()]


def _seeded(tmp_path, docs):
    c = Corpus(tmp_path)
    c.serve(docs)
    c.summary()
    return c


# --------------------------------------------------------------------------- #


def test_fresh_fetch_writes_the_corpus_and_reports_full(tmp_path):
    c = Corpus(tmp_path)
    c.serve([_doc(i) for i in (1, 2, 3)])
    s, _ = c.summary()
    assert s["mode"] == "full"
    assert (s["videos"], s["new_videos"], s["stored_videos"]) == (3, 3, 0)
    assert c.ids() == ["1:vid01", "1:vid02", "1:vid03"]


def test_rerun_with_nothing_new_appends_nothing(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    before = c.path.read_bytes()
    s, _ = c.summary()
    assert s["mode"] == "incremental"
    assert (s["new_videos"], s["stored_videos"], s["videos"]) == (0, 3, 3)
    assert s["with_transcript"] == 3 and s["coverage"] == 1.0
    assert c.path.read_bytes() == before   # not even an empty gzip member


def test_rerun_appends_exactly_the_rows_after_the_cursor(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    c.serve([_doc(i) for i in (1, 2, 3, 4, 5)])
    s, _ = c.summary()
    assert s["mode"] == "incremental"
    assert (s["new_videos"], s["stored_videos"], s["videos"]) == (2, 3, 5)
    ids = c.ids()
    assert ids == [f"1:vid0{i}" for i in range(1, 6)]   # kept in sort order
    assert len(ids) == len(set(ids))                    # never duplicated


def test_coverage_counts_the_whole_corpus_not_just_the_appended_rows(tmp_path):
    c = _seeded(tmp_path, [_doc(1), _doc(2, transcript=False)])
    c.serve([_doc(1), _doc(2, transcript=False), _doc(3)])
    s, _ = c.summary()
    assert (s["videos"], s["with_transcript"]) == (3, 2)
    assert s["coverage"] == 0.67


def test_truncated_last_line_falls_back_to_a_full_refetch(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    # A killed run leaves a half-written gzip member: the compressed spelling
    # of a truncated last line, and just as unusable.
    half = gzip.compress(b'{"id": "1:vid04", "cues": [[1.0, "half a line"]]}\n')
    with open(c.path, "ab") as f:
        f.write(half[:len(half) // 2])
    s, proc = c.summary()
    assert "unreadable" in proc.stderr                  # loud, on stderr
    assert s["mode"] == "full"
    assert (s["videos"], s["stored_videos"]) == (3, 0)
    assert c.ids() == ["1:vid01", "1:vid02", "1:vid03"]


def test_full_flag_refetches_from_scratch(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    c.serve([_doc(i) for i in (1, 2, 3, 4)])
    s, _ = c.summary("--full")
    assert s["mode"] == "full"
    assert (s["new_videos"], s["stored_videos"], s["videos"]) == (4, 0, 4)
    assert c.ids() == [f"1:vid0{i}" for i in range(1, 5)]


def test_mid_sweep_failure_leaves_the_stored_corpus_untouched(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    good = c.path.read_bytes()
    c.serve([_doc(i) for i in (1, 2, 3, 4, 5)])
    # let the append fetch its first page, then break the next call: rows are
    # already in the temp file when the sweep dies.
    spent = int(c.calls.read_text().strip())
    proc = c.run(fail_after=spent + 1)
    assert proc.returncode != 0
    assert c.path.read_bytes() == good       # the promised census survives


# --------------------------------------------------------------------------- #
# the gzipped store
# --------------------------------------------------------------------------- #
def test_store_is_gzip_and_deterministic(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    assert c.path.read_bytes()[:2] == b"\x1f\x8b"        # really gzip
    assert not (c.path.parent / "corpus.jsonl").exists()  # no plain twin
    first = c.path.read_bytes()
    c.run("--full")
    # mtime=0 + empty stored filename: same rows compress to the same bytes
    assert c.path.read_bytes() == first


def test_incremental_append_writes_a_second_member_readers_see_whole(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    c.serve([_doc(i) for i in range(1, 6)])
    c.summary()
    raw = c.path.read_bytes()
    # concatenated members, not a rewrite: the stored bytes are still a prefix
    assert raw.count(b"\x1f\x8b") >= 2
    assert c.ids() == [f"1:vid0{i}" for i in range(1, 6)]
    # and the appended member alone decompresses to just the new rows
    assert json.loads(c.text().splitlines()[-1])["id"] == "1:vid05"


def test_a_plain_corpus_from_an_older_run_still_seeds_an_append(tmp_path):
    c = _seeded(tmp_path, [_doc(i) for i in (1, 2, 3)])
    legacy = c.path.parent / "corpus.jsonl"
    legacy.write_text(c.text(), encoding="utf-8")
    c.path.unlink()
    c.serve([_doc(i) for i in (1, 2, 3, 4)])
    s, _ = c.summary()
    assert s["mode"] == "incremental"
    assert (s["new_videos"], s["stored_videos"], s["videos"]) == (1, 3, 4)
    assert c.path.exists() and c.ids() == [f"1:vid0{i}" for i in range(1, 5)]


def test_scan_reads_a_plain_corpus_named_without_gz(tmp_path):
    """Every corpus reader resolves .gz first and falls back to the plain
    file, so a path typed as `corpus.jsonl` works under either store."""
    plain = tmp_path / "corpus.jsonl"
    plain.write_text('{"id": "1:a"}\n', encoding="utf-8")
    with fetch_corpus.open_corpus(plain) as f:
        assert f.read() == '{"id": "1:a"}\n'
    with fetch_corpus.open_corpus_write(tmp_path / "corpus.jsonl.gz") as f:
        f.write('{"id": "1:b"}\n')
    # the .gz now wins for the same requested name
    with fetch_corpus.open_corpus(plain) as f:
        assert f.read() == '{"id": "1:b"}\n'
