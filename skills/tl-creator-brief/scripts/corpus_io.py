#!/usr/bin/env python3
"""The one home for the local transcript store's on-disk convention.

A corpus file is JSONL, gzipped by default and readable either way:

    {"id", "title", "publication_date", "views", "duration", "content_type",
     "cues": [[start_seconds, text], ...]}    # [] = no transcript stored

Captions compress ~8x and a back catalogue runs to hundreds of megabytes, so
the store is written gzipped; readers here accept either form, so a plain
``corpus.jsonl`` from an older run still opens and nothing on disk goes stale.
``open_corpus`` / ``open_corpus_write`` are that convention's single home —
every sibling script imports them from here rather than opening the store
itself. ``cues`` is the caption-XML parser the same readers need to rebuild a
timed cue list.

Not a command: this module is imported, never run.
"""
from __future__ import annotations

import contextlib
import gzip
import html
import io
import pathlib
import re

CUE = re.compile(r'<text start="([\d.]+)"[^>]*>(.*?)</text>', re.S)
TAG = re.compile(r"<[^>]+>")

GZIP_MAGIC = b"\x1f\x8b"
# Compression is single-threaded and these files run to hundreds of megabytes,
# so the level is a real time/space trade. COMPRESS_LEVEL is the fast end for
# bulk window records; CORPUS_LEVEL is the slower, smaller end used for the
# durable corpus, whose write sits behind a network sweep that dwarfs the
# difference.
COMPRESS_LEVEL = 1
CORPUS_LEVEL = 6


def resolve_corpus(path: str | pathlib.Path) -> pathlib.Path:
    """The file a reader should actually open for ``path``.

    A caller may name either form. ``corpus.jsonl`` resolves to the gzipped
    ``corpus.jsonl.gz`` when that exists (what the fetch writes today) and
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
    members are transparent to the reader: it sees one continuous line stream.
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
    the end of an existing file; concatenated members are a valid gzip stream.
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
