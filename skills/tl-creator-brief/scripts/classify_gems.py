#!/usr/bin/env python3
"""The scripted extractor: one batch, one request, one extract file.

Sends the SAME self-contained message the extractor agents get
(``extractor_prompt.render``) to an OpenAI-compatible chat endpoint — one
request per batch file — and writes each response to
``<returns>/batch-NNN.extract.json``, exactly where the agent fan-out writes
its files. ``assemble_extracts.py`` then validates and assembles both
transports identically; this script checks only that the response parses as an
object carrying ``gems`` and ``not_gems`` lists (the retry decision), never
spans, enums or counts.

Resumable within one fetch: a batch whose return file already exists is
skipped unless ``--force``. A batch still malformed after the retries writes
nothing and counts as an error, so the assembler sees a missing return file
for it and lists its windows for a re-judge.

Configuration comes from the environment (never hardcoded paths or keys):

* ``CREATOR_BRIEF_LLM_API_KEY`` — the key; falls back to ``OPENROUTER_API_KEY``
  in the environment, then to the ``OPENROUTER_API_KEY=`` line of
  ``--env-file`` (default ``~/.config/openrouter/.env``, read only if it
  exists). With no key at all the script writes a ``FALLBACK_REQUIRED`` marker
  line and exits with code 20, so the skill can branch to the extractor agent
  fan-out mechanically.
* ``CREATOR_BRIEF_LLM_BASE_URL`` — default ``https://openrouter.ai/api/v1``.
* ``CREATOR_BRIEF_LLM_MODEL``    — default ``deepseek/deepseek-v3.2``.
* ``CREATOR_BRIEF_LLM_CONCURRENCY`` — parallel requests, default 16 (1–64).

Usage:
    classify_gems.py --batches tl-creator-profiles/.corpus/<id>/batches \\
        --context context.json [--returns <dir>] [--concurrency N] [--force]
    # context.json: {"channel_name", "host_names", "known_facts",
    #                "format_label", "format_evidence"} — the same context
    #                block the extractor contract requires.

Output: one ``batch-NNN.extract.json`` per batch in ``--returns`` (default
``<batches>/../returns``), one JSON summary on stdout, and one ``FUNNEL`` line
on stderr for the run report. Raw transcript text stays in the files; only
counts and paths reach the orchestrator.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import extractor_prompt

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v3.2"
DEFAULT_ENV_FILE = "~/.config/openrouter/.env"
CONCURRENCY = 16     # env-tunable: CREATOR_BRIEF_LLM_CONCURRENCY
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 64
RETRIES = 2          # attempts per batch beyond the first
TIMEOUT = 180
# Exit code for "no API key": distinct from argparse's usage exit (2) and from
# the "finished with errors" exit (1), so the skill branches on it mechanically.
EXIT_FALLBACK_REQUIRED = 20

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def funnel(**fields) -> None:
    """One machine-parseable stage line for the run report (stderr)."""
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def read_env_file(path: str | pathlib.Path) -> str | None:
    """The ``OPENROUTER_API_KEY`` value from a KEY=VALUE file, if it exists."""
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "OPENROUTER_API_KEY":
            return v.strip().strip('"').strip("'") or None
    return None


def resolve_key(env_file: str | pathlib.Path) -> str | None:
    """CREATOR_BRIEF_LLM_API_KEY, else OPENROUTER_API_KEY, else the file."""
    return (os.environ.get("CREATOR_BRIEF_LLM_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or read_env_file(env_file))


def parse_extract(content: str, batch: str, n: int) -> dict | None:
    """The response as the extract object, or None when it is malformed.

    Accepts a bare object and a code-fenced one, with or without the
    ``batch``/``windows`` keys (they are filled in). Anything that is not an
    object with list-valued ``gems`` and ``not_gems`` is malformed.
    """
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(FENCE.sub("", content.strip()))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("gems"), list):
        return None
    if not isinstance(data.get("not_gems"), list):
        return None
    out = {"batch": data.get("batch") or batch,
           "windows": data.get("windows") if isinstance(
               data.get("windows"), int) else n}
    out.update({k: v for k, v in data.items()
                if k not in ("batch", "windows")})
    return out


def call_api(base_url: str, key: str, model: str, prompt: str) -> tuple:
    """(content string | None, error | None, usage dict)."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 # harmless attribution headers the endpoint may ignore
                 "HTTP-Referer": "https://github.com/ThoughtLeaders-io/thoughtleaders-cli",
                 "X-Title": "tl-creator-brief"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            d = json.loads(resp.read().decode())
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", {}
    if "error" in d:
        return None, json.dumps(d["error"])[:300], {}
    try:
        content = d["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        return None, f"unexpected response shape: {e}", {}
    return content, None, d.get("usage") or {}


def env_concurrency() -> int:
    raw = os.environ.get("CREATOR_BRIEF_LLM_CONCURRENCY")
    if not raw:
        return CONCURRENCY
    try:
        n = int(raw)
    except ValueError:
        print(f"CREATOR_BRIEF_LLM_CONCURRENCY={raw!r} is not an integer; "
              f"using {CONCURRENCY}", file=sys.stderr)
        return CONCURRENCY
    return max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, n))


def main() -> None:
    started = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", required=True,
                    help="batches/ directory of window files")
    ap.add_argument("--context", required=True,
                    help="JSON file with the extractor context block: "
                         "channel_name, host_names, known_facts, "
                         "format_label, format_evidence")
    ap.add_argument("--returns", default=None,
                    help="directory for batch-NNN.extract.json "
                         "(default: <batches>/../returns)")
    ap.add_argument("--concurrency", type=int, default=None,
                    help=f"parallel requests (default: "
                         f"$CREATOR_BRIEF_LLM_CONCURRENCY or {CONCURRENCY})")
    ap.add_argument("--force", action="store_true",
                    help="re-send batches whose return file already exists")
    ap.add_argument("--env-file", default=DEFAULT_ENV_FILE,
                    help=f"file to read OPENROUTER_API_KEY from when neither "
                         f"env var is set (default {DEFAULT_ENV_FILE}; read "
                         f"only if it exists)")
    a = ap.parse_args()
    concurrency = (env_concurrency() if a.concurrency is None else
                   max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, a.concurrency)))

    # The batch files are on disk before anything else is decided: the no-key
    # fallback consumes exactly these files, so the run must be able to point
    # at a counted, existing batch set even when this script does no work.
    batch_dir = pathlib.Path(a.batches).resolve()
    batch_files = sorted(batch_dir.glob("batch-*.json"))
    batches = [(p, json.loads(p.read_text(encoding="utf-8")))
               for p in batch_files]
    total_windows = sum(len(w) for _, w in batches)
    if not total_windows:
        sys.exit(f"no batch files in {batch_dir}")

    key = resolve_key(a.env_file)
    if not key:
        print(f"FALLBACK_REQUIRED reason=missing_api_key "
              f"batches_dir={batch_dir} batch_files={len(batch_files)} "
              f"windows={total_windows}", file=sys.stderr)
        print("No API key is configured (CREATOR_BRIEF_LLM_API_KEY, "
              "OPENROUTER_API_KEY, or the --env-file). The batch files above "
              "are already written and unjudged: fall back to the extractor "
              "agent fan-out (one agent per batch file, ALL spawned in one "
              "message) per references/transcript-mining.md, Layer 3.",
              file=sys.stderr)
        funnel(stage="extract", path="fallback_required",
               windows=total_windows, batches=len(batch_files),
               written=0, errors=0,
               elapsed_s=round(time.monotonic() - started, 1))
        sys.exit(EXIT_FALLBACK_REQUIRED)
    base_url = os.environ.get("CREATOR_BRIEF_LLM_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("CREATOR_BRIEF_LLM_MODEL", DEFAULT_MODEL)

    returns = (pathlib.Path(a.returns) if a.returns
               else batch_dir.parent / "returns")
    returns.mkdir(parents=True, exist_ok=True)
    context = json.loads(pathlib.Path(a.context).read_text(encoding="utf-8"))
    rubric = extractor_prompt.load_rubric()
    evidence = extractor_prompt.load_evidence()

    lock = threading.Lock()
    stats = {"written": 0, "errors": 0, "skipped": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "largest": 0}

    def work(item: tuple[pathlib.Path, list[dict]]) -> None:
        path, windows = item
        n = extractor_prompt.batch_number(path)
        target = returns / f"batch-{n}.extract.json"
        if target.exists() and not a.force:
            with lock:
                stats["skipped"] += 1
                print(f"  batch {n}: skipped (return file exists)",
                      file=sys.stderr)
            return
        prompt = extractor_prompt.render(windows, context, rubric, evidence,
                                         batch=n, write_to=None)
        obj, err = None, "not_attempted"
        for _ in range(1 + RETRIES):
            content, err, usage = call_api(base_url, key, model, prompt)
            with lock:
                stats["prompt_tokens"] += usage.get("prompt_tokens") or 0
                stats["completion_tokens"] += usage.get(
                    "completion_tokens") or 0
            if err is None:
                obj = parse_extract(content, n, len(windows))
                if obj is not None:
                    break
                err = "malformed: not an object with gems/not_gems lists"
        with lock:
            if obj is None:
                stats["errors"] += 1
                print(f"  batch {n}: ERROR {err}", file=sys.stderr)
                return
            text = json.dumps(obj, ensure_ascii=False)
            target.write_text(text, encoding="utf-8")
            stats["written"] += 1
            stats["largest"] = max(stats["largest"], len(text))
            print(f"  batch {n}: {len(obj.get('gems') or [])} gems "
                  f"({stats['written']}/{len(batches)} written, "
                  f"{stats['errors']} errors)", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(work, batches))

    elapsed = round(time.monotonic() - started, 1)
    print(json.dumps({
        "model": model,
        "concurrency": concurrency,
        "batches": len(batches),
        "batches_written": stats["written"],
        "skipped_existing": stats["skipped"],
        "errors": stats["errors"],
        "windows": total_windows,
        "prompt_tokens": stats["prompt_tokens"],
        "completion_tokens": stats["completion_tokens"],
        "elapsed_s": elapsed,
        "returns_dir": str(returns),
        "largest_return_chars": stats["largest"],
    }, indent=1))
    funnel(stage="extract", path="api", model=model, batches=len(batches),
           windows=total_windows, written=stats["written"],
           errors=stats["errors"], prompt_tokens=stats["prompt_tokens"],
           completion_tokens=stats["completion_tokens"], elapsed_s=elapsed)
    sys.exit(1 if stats["errors"] else 0)


if __name__ == "__main__":
    main()
