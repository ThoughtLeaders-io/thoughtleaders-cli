#!/usr/bin/env python3
"""Probe ES for keyword document counts.

For each keyword, sends one `size:0` + `track_total_hits` phrase probe to
`tl db es` against the `title`, `summary`, and `transcript` fields, then
prints a single JSON object with the keywords sorted descending by document
count.

Usage:
    probe.py crypto bitcoin "smart contract"
    echo '["crypto","bitcoin"]' | probe.py
    probe.py --since 2025-01-01 --until 2026-01-01 crypto bitcoin

Output (stdout):
    {"keywords": [{"keyword": "crypto", "count": 18742}, ...]}
"""
import argparse
import json
import subprocess
import sys

DEFAULT_FIELDS = ["title", "summary", "transcript"]
PROBE_TIMEOUT = 60  # per-keyword ES probe, seconds


def build_body(keyword, fields, since, until):
    multi_match = {
        "multi_match": {
            "query": keyword,
            "type": "phrase",
            "fields": fields,
        }
    }
    if not since and not until:
        query = multi_match
    else:
        date_range = {}
        if since:
            date_range["gte"] = since
        if until:
            date_range["lte"] = until
        query = {
            "bool": {
                "must": [multi_match],
                "filter": [{"range": {"publication_date": date_range}}],
            }
        }
    return {"size": 0, "track_total_hits": True, "query": query}


def extract_total(data):
    total = data.get("total")
    if isinstance(total, int):
        return total
    hits = data.get("hits")
    if isinstance(hits, dict):
        ht = hits.get("total")
        if isinstance(ht, dict) and isinstance(ht.get("value"), int):
            return ht["value"]
        if isinstance(ht, int):
            return ht
    return 0


def probe(keyword, fields, since, until):
    body = build_body(keyword, fields, since, until)
    proc = subprocess.run(
        ["tl", "db", "es", "-", "--json"],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"tl db es failed for {keyword!r} (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}\n"
        )
        sys.exit(proc.returncode or 1)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"could not parse tl db es output for {keyword!r}: {exc}\n"
        )
        sys.exit(1)
    return extract_total(data)


def collect_keywords(argv_words):
    if argv_words:
        return [w.strip() for w in argv_words if w.strip()]
    if sys.stdin.isatty():
        return []
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()]
    sys.exit("stdin JSON must be a list of strings")


def dedupe_case_insensitive(items):
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Rank keywords by Elasticsearch document count across title/summary/transcript."
    )
    ap.add_argument("keywords", nargs="*", help="Keywords (or pipe a JSON array on stdin)")
    ap.add_argument("--since", help="publication_date >= YYYY-MM-DD")
    ap.add_argument("--until", help="publication_date <= YYYY-MM-DD")
    ap.add_argument(
        "--operator",
        choices=["AND", "OR"],
        default="OR",
        help="How the caller intends to combine these keywords downstream (default: OR). Echoed in the output envelope as `operator`.",
    )
    ap.add_argument(
        "--fields",
        default=",".join(DEFAULT_FIELDS),
        help=f"Comma-separated ES fields to probe with `multi_match phrase` (default: {','.join(DEFAULT_FIELDS)}). Use to scope probes to per-report-type field sets.",
    )
    args = ap.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    if not fields:
        sys.exit("--fields must list at least one ES field")

    keywords = dedupe_case_insensitive(collect_keywords(args.keywords))
    if not keywords:
        sys.exit("provide at least one keyword (positional args or JSON array on stdin)")

    results = [
        {"keyword": kw, "count": probe(kw, fields, args.since, args.until)}
        for kw in keywords
    ]
    results.sort(key=lambda r: r["count"], reverse=True)
    print(json.dumps({"operator": args.operator, "keywords": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
