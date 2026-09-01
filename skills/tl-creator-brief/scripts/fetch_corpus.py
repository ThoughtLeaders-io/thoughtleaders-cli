#!/usr/bin/env python3
"""One paged ES sweep brings EVERY transcript of a channel home.

All selection intelligence runs locally over this store, and the model layer
sees ranked windows, never raw dumps. Deterministic: same channel -> same
local corpus, byte for byte.

One ``search_after`` walk over the whole catalogue — no per-video fetch loop,
no read cap, no sampling. Videos without a stored transcript come back from
the same sweep without the field, so transcript coverage is a census taken for
free rather than a second query. A query failure aborts loudly; it is never
recorded as a coverage gap.

A rerun is incremental by default: when a complete corpus for the channel is
already on disk, only uploads published after its last stored row are fetched
and appended, so a second run costs seconds instead of a full catalogue sweep.
``--full`` forces the from-scratch sweep. Incrementality only sees NEW
uploads — an edited title or a re-transcribed old video is not revisited;
``--full`` is the refresh path for that.

Usage:
    fetch_corpus.py --channel <id>
    fetch_corpus.py --channel <id> --out tl-creator-profiles/.corpus
    fetch_corpus.py --channel <id> --full     # ignore + replace what's stored

Output (stdout): one JSON summary. The corpus itself is written to
``<out>/<channel_id>/corpus.jsonl.gz`` (gzip, one video per JSON line):
    {"id", "title", "publication_date", "views", "duration", "content_type",
     "cues": [[start_seconds, text], ...]}    # [] = no transcript stored

The store is gzipped because captions compress ~8x and a back catalogue runs
to hundreds of megabytes. Readers here accept either form — a plain
``corpus.jsonl`` from an older run still opens — so nothing on disk goes
stale. ``open_corpus`` / ``open_corpus_write`` are the one home for that
convention; every sibling script imports them from here rather than opening
the store itself.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import html
import io
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data

PAGE = 500
FIELDS = ["id", "title", "publication_date", "views", "duration",
          "content_type", "transcript", "transcript_language"]

CUE = re.compile(r'<text start="([\d.]+)"[^>]*>(.*?)</text>', re.S)
TAG = re.compile(r"<[^>]+>")

GZIP_MAGIC = b"\x1f\x8b"
# Compression is single-threaded and these files run to hundreds of megabytes,
# so the level is a real time/space trade. The default is the fast end: the
# scan's window record is the big one (measured on a 477K-window scan: level 1
# costs +2s and shrinks it 6.1x, level 6 costs +6s for 7.3x). The corpus this
# script writes takes the slower, smaller end instead — it is the durable
# artifact, re-read by every rescan, and its write sits behind a network sweep
# that dwarfs the difference.
COMPRESS_LEVEL = 1
CORPUS_LEVEL = 6


# --------------------------------------------------------------------------- #
# the local store: gzipped by default, plain still readable
# --------------------------------------------------------------------------- #
def resolve_corpus(path: str | pathlib.Path) -> pathlib.Path:
    """The file a reader should actually open for ``path``.

    A caller may name either form. ``corpus.jsonl`` resolves to the gzipped
    ``corpus.jsonl.gz`` when that exists (what this script writes today) and
    otherwise stays as given, so a corpus fetched before the store was
    compressed keeps working untouched.
    """
    p = pathlib.Path(path)
    if p.suffix == ".gz":
        return p
    gz = p.with_name(p.name + ".gz")
    return gz if gz.exists() else p


def open_corpus(path: str | pathlib.Path):
    """Open a corpus (or windows) file for reading text, gzipped or not.

    The compression is sniffed from the file's magic bytes rather than its
    name, so a misnamed file reads correctly either way. Concatenated gzip
    members — what an incremental append writes — are transparent to the
    reader: it sees one continuous line stream.
    """
    p = resolve_corpus(path)
    with open(p, "rb") as probe:
        gzipped = probe.read(2) == GZIP_MAGIC
    if gzipped:
        return gzip.open(p, "rt", encoding="utf-8")
    return open(p, encoding="utf-8")


@contextlib.contextmanager
def open_corpus_write(path: str | pathlib.Path, *, append: bool = False,
                      level: int = COMPRESS_LEVEL):
    """Write text into a gzip file, deterministically.

    ``mtime=0``, an empty stored filename and a fixed compression level keep
    the bytes a pure function of the content — the same corpus compresses to
    the same file on every run. ``append=True`` starts a NEW gzip member at
    the end of an existing file; concatenated members are a valid gzip
    stream, so the incremental path can copy the stored file and append only
    the new rows.
    """
    raw = open(path, "ab" if append else "wb")
    try:
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0,
                           compresslevel=level)
        with io.TextIOWrapper(gz, encoding="utf-8") as text:
            yield text
    finally:
        raw.close()


def _unescape(text: str) -> str:
    """Unescape to a fixed point: caption text is sometimes double-escaped
    (``&amp;#39;``), so a single pass leaves ``&#39;`` behind."""
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


def cues(raw: str | None) -> list[tuple[float, str]]:
    """Caption XML -> [(start_seconds, text)]."""
    out = []
    for start, body in CUE.findall(raw or ""):
        text = _unescape(TAG.sub(" ", body)).replace("\n", " ").strip()
        if text:
            out.append((float(start), re.sub(r"\s+", " ", text)))
    return out


def scan_existing(path: pathlib.Path) -> tuple[int, int, list] | None:
    """Read a stored corpus: (videos, with_transcript, search_after cursor).

    ``None`` means "unusable, refetch from scratch" — an unparseable line or a
    truncated compressed stream (a corpus killed mid-run) or a last row with
    no sort key. Counting here is what lets the summary keep reporting
    whole-corpus coverage after an append-only run.
    """
    n_total = n_with = 0
    last = None
    try:
        with open_corpus(path) as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                n_total += 1
                if row.get("cues"):
                    n_with += 1
                last = row
    except (json.JSONDecodeError, EOFError, OSError):
        # OSError covers gzip.BadGzipFile: a half-written compressed member
        # is the compressed spelling of a truncated last line.
        return None
    if not n_total or not isinstance(last, dict):
        return None
    if last.get("publication_date") is None or last.get("id") is None:
        return None
    return n_total, n_with, [last["publication_date"], last["id"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, required=True,
                    help="internal TL channel id, from `tl channels find`")
    ap.add_argument("--out", default="tl-creator-profiles/.corpus",
                    help="corpus root; the channel id becomes a subdirectory, "
                         "so concurrent runs on different channels never "
                         "collide")
    ap.add_argument("--full", action="store_true",
                    help="refetch the whole catalogue instead of appending "
                         "only uploads newer than the stored corpus (the "
                         "default when one exists). Use it to pick up edited "
                         "or re-transcribed old videos.")
    a = ap.parse_args()
    out = pathlib.Path(a.out) / str(a.channel)
    out.mkdir(parents=True, exist_ok=True)

    # Write to a sibling temp file and rename only after the last page lands:
    # a timeout / credit failure mid-sweep must never leave a valid-looking
    # partial corpus (or clobber a previous complete one) — a later scan
    # could not tell it from the promised census.
    final = out / "corpus.jsonl.gz"
    partial = out / "corpus.jsonl.gz.partial"
    # A corpus fetched before the store was compressed still seeds an
    # incremental run; this run then writes the gzipped file, which every
    # reader prefers from that point on.
    stored = resolve_corpus(out / "corpus.jsonl")

    # Incremental by default: the stored corpus's last row is the cursor, and
    # the copy that seeds the temp file keeps the same all-or-nothing rename —
    # a failure mid-sweep leaves the previous complete corpus untouched.
    after, n_stored, n_with = None, 0, 0
    mode = "full"
    if not a.full and stored.exists() and stored.stat().st_size > 0:
        seed = scan_existing(stored)
        if seed is None:
            print(f"stored corpus {stored} is unreadable (truncated line?) — "
                  f"refetching in full", file=sys.stderr)
        else:
            n_stored, n_with, after = seed
            mode = "incremental"

    if mode == "incremental":
        if stored.suffix == ".gz":
            # Byte copy, then a second gzip member holding only the new rows:
            # appending never recompresses what is already stored.
            shutil.copyfile(stored, partial)
        else:
            with open_corpus(stored) as src, \
                    open_corpus_write(partial, level=CORPUS_LEVEL) as dst:
                shutil.copyfileobj(src, dst)
    n_new = 0
    # The writer opens on the first row, so a rerun that finds nothing new
    # appends no gzip member at all and leaves the stored bytes untouched.
    with contextlib.ExitStack() as stack:
        f = None
        while True:
            body = {"size": PAGE,
                    "query": {"bool": {"filter": [
                        {"term": {"doc_type": "article"}},
                        {"term": {"channel.id": a.channel}}]}},
                    "_source": FIELDS,
                    "sort": [{"publication_date": "asc"}, {"id": "asc"}]}
            if after:
                body["search_after"] = after
            rows = tl_data.db_es(body)
            if not rows:
                break
            if f is None:
                f = stack.enter_context(open_corpus_write(
                    partial, append=(mode == "incremental"),
                    level=CORPUS_LEVEL))
            for r in rows:
                n_new += 1
                c = cues(r.pop("transcript", None))
                if c:
                    n_with += 1
                r["cues"] = c            # [] = no transcript: census for free
                f.write(json.dumps(r, default=str) + "\n")
            after = [rows[-1].get("publication_date"), rows[-1].get("id")]

    n_total = n_stored + n_new
    if n_total == 0:
        partial.unlink(missing_ok=True)
        sys.exit(f"no uploads found for channel {a.channel}")
    partial.replace(final)

    print(json.dumps({
        "channel": a.channel, "videos": n_total,
        "with_transcript": n_with,
        "coverage": round(n_with / n_total, 2),
        "corpus": str(final),
        "mode": mode,
        "new_videos": n_new,
        "stored_videos": n_stored,
        "note": "all transcripts fetched; nothing sampled away"
                if mode == "full" else
                "appended uploads newer than the stored corpus; "
                "--full refetches everything"}))


if __name__ == "__main__":
    main()
