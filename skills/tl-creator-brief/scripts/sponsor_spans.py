#!/usr/bin/env python3
"""Spoken sponsored segments per video, looked up in bulk.

The one home for the ad-read span lookup: a video's sponsored brand mentions
carry the seconds the read occupies, which is what tells a passage apart from
an ad read it happens to sit inside. Only a mention that is both *sponsored*
and located *in the transcript* counts, so an organic mention or a
description-only mention in the same video never poisons the span list.

A query failure raises — it is never a silent empty span list. The caller
decides what to do with that (``fetch_cues.py`` falls back to its regex
heuristic and records which source it used).

Not a command: this module is imported, never run.
"""
from __future__ import annotations

import pathlib
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data  # noqa: E402

SPONSOR_PAD = 75      # an ad read runs past the seconds the detector flags
IDS_CHUNK = 1000
ES_CONCURRENCY = 4    # parallel id-chunk fetches for the sponsor-span lookup


def _sponsor_chunk(chunk: list[str]) -> dict[str, list[tuple[float, float]]]:
    """One id-chunk's spans. Any query failure propagates to the caller."""
    rows = tl_data.db_es({
        "size": len(chunk),
        "query": {"ids": {"values": chunk}},
        "_source": ["id", "brand_mentions"],
    })
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        mentions = row.get("brand_mentions") or []
        if isinstance(mentions, dict):
            mentions = [mentions]
        for m in mentions:
            if m.get("type") != "sponsored" or m.get("field") != "transcript":
                continue
            start, end = m.get("start_ts"), m.get("end_ts")
            if not isinstance(start, (int, float)):
                continue
            if not isinstance(end, (int, float)) or end < start:
                end = start
            # (0, 0) is a detection with no located position; padded, it
            # would wrongly claim the opening of the video as an ad read.
            if start <= 0 and end <= 0:
                continue
            out[str(row.get("id"))].append((float(start), float(end)))
    return out


def sponsor_segments(refs: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Spoken sponsored segments per video, batched over the id list.

    Every mention is re-checked individually: only ``type == "sponsored"`` AND
    ``field == "transcript"`` counts. A query failure raises — it is never a
    silent empty span list.

    Id chunks are fetched concurrently, but merged strictly in chunk order and
    a video's ids never straddle two chunks, so the resulting span lists are
    the same lists in the same order as a serial fetch.
    """
    chunks = [refs[i:i + IDS_CHUNK] for i in range(0, len(refs), IDS_CHUNK)]
    if not chunks:
        return {}
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=min(ES_CONCURRENCY,
                                            len(chunks))) as pool:
        for part in pool.map(_sponsor_chunk, chunks):
            for ref, spans in part.items():
                out[ref].extend(spans)
    return dict(out)
