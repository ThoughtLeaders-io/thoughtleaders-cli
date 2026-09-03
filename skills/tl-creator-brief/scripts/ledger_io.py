#!/usr/bin/env python3
"""The one reader and writer for a creator ledger (``<channel_id>-facts.jsonl``).

A ledger is one JSONL file. Its FIRST line may be the meta record — an object
whose ``schema`` starts with ``tl-creator-meta/`` (what the build was: when,
over which videos, what it found; see ``references/profile-spec.md``). Every
following line is one fact. Nothing in the repo iterates a ledger's lines
raw: go through ``read_ledger`` / ``iter_facts`` so the header is never
mistaken for a fact, and through ``write_ledger`` so the file is written
atomically with the header first.

A working ``facts.jsonl`` inside ``.corpus/<id>/`` has no header; the reader
returns ``meta=None`` for it and the same fact list.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Iterator

META_SCHEMA_PREFIX = "tl-creator-meta/"


def is_meta(obj: object) -> bool:
    return isinstance(obj, dict) and str(obj.get("schema") or "").startswith(META_SCHEMA_PREFIX)


def _lines(path: pathlib.Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{n}: not JSON ({exc})") from exc
            if not isinstance(obj, dict):
                raise SystemExit(f"{path}:{n}: expected an object, got {type(obj).__name__}")
            yield obj


def read_ledger(path: str | os.PathLike) -> tuple[dict | None, list[dict]]:
    """``(meta, facts)`` — ``meta`` is None when the file carries no header.
    A meta record anywhere but the first line is an error, not a fact."""
    path = pathlib.Path(path)
    meta: dict | None = None
    facts: list[dict] = []
    for i, obj in enumerate(_lines(path)):
        if is_meta(obj):
            if i != 0:
                raise SystemExit(f"{path}: meta record on line {i + 1}; it must be the first line")
            meta = obj
            continue
        facts.append(obj)
    return meta, facts


def iter_facts(path: str | os.PathLike) -> Iterator[dict]:
    for obj in _lines(pathlib.Path(path)):
        if not is_meta(obj):
            yield obj


def count_facts(path: str | os.PathLike) -> int:
    return sum(1 for _ in iter_facts(path))


def write_ledger(path: str | os.PathLike, meta: dict | None, facts: list[dict]) -> pathlib.Path:
    """Header first (when given), one fact per line, written to a sibling
    temp file and renamed into place so a reader never sees a half file."""
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".partial")
    with open(tmp, "w", encoding="utf-8") as fh:
        if meta is not None:
            if not is_meta(meta):
                raise ValueError("meta record must carry a tl-creator-meta/* schema")
            fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for fact in facts:
            if is_meta(fact):
                raise ValueError("a fact cannot carry a meta schema")
            fh.write(json.dumps(fact, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path
