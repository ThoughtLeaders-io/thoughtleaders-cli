"""Local repeat-query detection for `tl db` commands.

Agents sometimes re-run the exact same raw query in a tight loop — losing
the result, or polling data that will not change — and every run is billed.
This module keeps a small local log of recent query hashes and decides when
a repeat warning is due. Everything is best-effort by design: state lives
in a JSON file next to the CLI config, concurrent runs may race it, and any
I/O or parse failure resets it — a heuristic warning must never break a
query.
"""

import hashlib
import json
import os
import time

from tl_cli.config import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / "recent_queries.json"

# A repeat is the same normalized query seen REPEAT_THRESHOLD+ times inside
# WINDOW_S. Warnings re-arm after WARN_INTERVAL_S so a long-running loop is
# nudged about once a minute rather than on every single run.
WINDOW_S = 300
REPEAT_THRESHOLD = 3
WARN_INTERVAL_S = 60

ENV_SUPPRESS = "TL_NO_REPEAT_WARNING"


def query_hash(engine: str, query: str, pricing: bool = False) -> str:
    """Stable digest for an (engine, query) pair.

    Whitespace runs and letter case don't change what a query does, so they
    don't change the digest. The engine and the --pricing flag do: the same
    text against pg vs fb, or a dry-run vs a real run, are different actions.
    """
    normalized = " ".join(query.split()).strip().rstrip(";").lower()
    basis = f"{engine}\x00{'pricing' if pricing else 'run'}\x00{normalized}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def record_and_check(digest: str) -> int | None:
    """Record one run of ``digest``; return the run count when a warning is due.

    Returns None below the threshold, while a warning from the last
    WARN_INTERVAL_S is still fresh, or when TL_NO_REPEAT_WARNING is set.
    """
    if os.environ.get(ENV_SUPPRESS):
        return None
    now = time.time()
    state = _load()
    entry = state.get(digest)
    entry = entry if isinstance(entry, dict) else {}
    runs = _recent_runs(entry, now)
    runs.append(now)
    warned_at = entry.get("warned_at")
    warning_fresh = isinstance(warned_at, int | float) and now - warned_at < WARN_INTERVAL_S
    due = len(runs) >= REPEAT_THRESHOLD and not warning_fresh
    state[digest] = {"runs": runs, "warned_at": now if due else warned_at}
    _save(state, now)
    return len(runs) if due else None


def _recent_runs(entry: dict, now: float) -> list[float]:
    raw = entry.get("runs")
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, int | float) and now - t < WINDOW_S]


def _load() -> dict:
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state: dict, now: float) -> None:
    pruned = {}
    for digest, entry in state.items():
        if not isinstance(entry, dict):
            continue
        runs = _recent_runs(entry, now)
        if runs:
            pruned[digest] = {"runs": runs, "warned_at": entry.get("warned_at")}
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(pruned, f)
    except OSError:
        pass
