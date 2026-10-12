#!/usr/bin/env python3
"""Shared data-access seam for skills that shell out to the ``tl`` CLI.

One wrapper instead of a copy per script. Import it with a two-line path hook
(no ``cd`` into any skill directory, so concurrent runs on different channels
never fight over a working directory):

    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
    import tl_data

(The module is deliberately NOT named ``tl_cli``: the installed package is,
and a path hook that shadows it is a debugging trap.)

Behaviour every consumer relies on:

* **Query bodies travel on stdin** (``tl db es -``), never argv, so a large
  ids list or SQL never hits an argument-length limit.
* **Every call has a timeout** (default 180s). One hung ``tl`` process must
  not stall a bulk run.
* **Failures are loud.** Auth, credit, plan and network errors raise; they are
  never converted into empty results, because an empty result is data and an
  error is not.
* **Failures are classified by the CLI's exit code**, never by parsing
  stderr: 2 auth required, 4 out of credits, 5 access denied, 3 rate-limit or
  server error, 1 other. The mapping is documented in AGENTS.md.

Public API:

    db_pg(sql)        -> list[dict]   rows
    db_fb(sql)        -> list[dict]   rows
    db_es(body: dict) -> list[dict]   rows (the CLI's ``results`` list)
    whoami()          -> dict
    preflight()       -> None         raises CliUnavailable if unusable
    query(engine, body) -> dict       the full envelope (totals, aggregations)
    prefetch([...])   -> None         batch independent reads (MCP sessions)

MCP sessions. When ``TL_MCP_SESSION`` names a session directory (set by
``mcp_run.py``), the same calls are answered from receipts of connected MCP
tool results instead of the ``tl`` CLI. A read with no receipt raises
``PendingRequest`` (a BaseException, so ``except Exception`` handlers in the
skills never swallow it); the runner turns that into a tool request for the
host, then replays the script once the host has ingested the result.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TL_BIN = os.environ.get("TL_CLI_BIN", "tl")
DEFAULT_TIMEOUT = 180


class CliUnavailable(RuntimeError):
    """The tl CLI cannot be used: missing, not authenticated, out of credits,
    or the account lacks the required plan/permission."""


class DataError(RuntimeError):
    """A query executed but failed or returned something unreadable."""


class IncompleteDataError(DataError):
    """A successful response was truncated and is unsafe to publish or cache."""


def _error(cls, message: str, exit_code: int):
    """Build an error carrying the CLI exit-code class (see module doc)."""
    exc = cls(message)
    exc.exit_code = exit_code
    return exc


def _require_complete(data) -> None:
    """Reject a successful response whose rows were cut by a billing quota."""
    if not isinstance(data, dict) or not data.get("_billing_quota_exhausted"):
        return
    retry = data.get("_billing_earliest_retry_at")
    quota = data.get("_billing_quota") or {}
    detail = []
    if quota.get("queries_max") is not None:
        detail.append(f"queries {quota.get('queries_used')}/{quota.get('queries_max')}")
    if quota.get("rows_max") is not None:
        detail.append(f"rows {quota.get('rows_used')}/{quota.get('rows_max')}")
    raise IncompleteDataError(
        "tl returned a quota-truncated response; no partial rows were accepted"
        + (f" ({', '.join(detail)})" if detail else "")
        + (f". Retry at {retry}" if retry else "")
    )


def _child_env() -> dict[str, str]:
    # Force UTF-8 in the child so `tl`'s output survives Windows consoles
    # whose default codec would mangle it before we ever see the JSON.
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _tl(args: list[str], *, input_text: str | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> str:
    exe = shutil.which(TL_BIN) or TL_BIN
    try:
        proc = subprocess.run(
            [exe, *args],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_child_env(),
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CliUnavailable(
            f"`{TL_BIN}` CLI not found on PATH. Install it (see the tl-setup "
            f"skill) and run `tl auth login`. ({exc})"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DataError(
            f"tl {' '.join(args[:3])} timed out after {timeout}s"
        ) from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode == 2:
            raise _error(CliUnavailable,
                         "tl CLI is not authenticated. Run `tl auth login` (or "
                         "set TL_API_KEY), then retry. " + err, 2)
        if proc.returncode == 4:
            raise _error(CliUnavailable, "tl CLI is out of credits: " + err, 4)
        if proc.returncode == 5:
            raise _error(CliUnavailable,
                         "tl CLI access denied (plan or permission): " + err, 5)
        if proc.returncode == 3:
            raise _error(DataError,
                         f"tl {' '.join(args[:3])} rate-limited or server error "
                         f"(retryable): {err[:500]}", 3)
        raise _error(DataError, f"tl {' '.join(args[:3])} failed: {err[:500]}",
                     proc.returncode)
    return proc.stdout


_TRANSIENT = ("timed out", "rate-limited or server error", "read operation timed out")
TRANSIENT_RETRIES = 1        # one more try, after a short pause
TRANSIENT_PAUSE_S = 3.0


def _tl_retrying(args: list[str], *, input_text: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT) -> str:
    """``_tl`` with one retry on a transient failure (a timed-out read, a
    rate limit, a 5xx). One slow Elasticsearch read must not end a run that
    spent an hour of agents before it; anything else propagates unchanged."""
    attempt = 0
    while True:
        try:
            return _tl(args, input_text=input_text, timeout=timeout)
        except CliUnavailable:
            raise
        except DataError as exc:
            msg = str(exc).lower()
            if attempt >= TRANSIENT_RETRIES or not any(t in msg for t in _TRANSIENT):
                raise
            attempt += 1
            time.sleep(TRANSIENT_PAUSE_S)


def _tl_json(args: list[str], *, input_text: str | None = None,
             timeout: int = DEFAULT_TIMEOUT):
    if os.environ.get("TL_MCP_SESSION"):
        data = _mcp(mcp_request(args, input_text))
        _require_complete(data)
        return data
    out = _tl_retrying(args, input_text=input_text, timeout=timeout).strip()
    if not out:
        return None
    try:
        data = json.loads(out)
        _require_complete(data)
        return data
    except json.JSONDecodeError as exc:
        raise DataError(
            f"tl {' '.join(args[:3])} returned non-JSON output: {out[:300]}"
        ) from exc


def _rows(data) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, dict):
        # Raw-data quota exhaustion can be a successful HTTP response whose
        # rows stop at the remaining allowance. Returning those rows as an
        # ordinary list turns "incomplete" into false evidence that no more
        # records exist.
        _require_complete(data)
        # A 200 with premium fields withheld carries "_upgrade_required"
        # next to the rows. Unwrapping past it would let a plan-gated run
        # read the gaps as "no data exists" (e.g. a complete-looking corpus
        # with no transcripts), so it fails loudly like any other denial.
        notice = data.get("_upgrade_required")
        if isinstance(notice, dict):
            fields = ", ".join(str(f) for f in notice.get("fields") or [])
            raise DataError(
                "tl withheld premium field(s) from this response"
                + (f" ({fields})" if fields else "") + ": "
                + (notice.get("message")
                   or "some fields are available on paid plans")
            )
        for key in ("results", "rows", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return list(data)


def db_pg(sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return _rows(_tl_json(["db", "pg", "-", "--json"], input_text=sql,
                          timeout=timeout))


def db_fb(sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return _rows(_tl_json(["db", "fb", "-", "--json"], input_text=sql,
                          timeout=timeout))


def db_es(body: dict, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    """Run an ES search body and return the rows.

    ``tl db es`` returns ``{"results": [...]}`` (flat rows), not the native
    ``hits.hits`` shape.
    """
    return _rows(_tl_json(["db", "es", "-", "--json"],
                          input_text=json.dumps(body), timeout=timeout))


def cli_rows(args: list[str], *, input_text: str | None = None,
             timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    """Run any ``tl`` command with ``--json`` and return unwrapped rows."""
    return _rows(_tl_json(args, input_text=input_text, timeout=timeout))


def whoami(*, timeout: int = DEFAULT_TIMEOUT) -> dict:
    data = _tl_json(["whoami", "--json"], timeout=timeout)
    return data if isinstance(data, dict) else {}


def preflight() -> None:
    """Confirm the tl CLI (or MCP session) is usable; raise CliUnavailable otherwise."""
    if os.environ.get("TL_MCP_SESSION"):
        whoami()
        return
    _tl(["whoami"], timeout=60)


# --------------------------------------------------------------------------- #
# MCP sessions: the same reads, answered by the host's connected MCP tools.
# --------------------------------------------------------------------------- #
CONTRACT_VERSION = 1
MCP_TOOLS = {"tl_db_pg", "tl_db_fb", "tl_db_es", "tl_whoami", "tl_channels_similar"}
PREFETCH_LIMIT = 100


class PendingRequest(BaseException):
    """No receipt yet for a read: suspend the script, never treat it as empty."""

    def __init__(self, requests: list[dict]):
        super().__init__(f"{len(requests)} MCP tool request(s) pending")
        self.requests = requests


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def mcp_request(args: list[str], input_text: str | None = None) -> dict:
    """Translate a ``tl`` argv into the connected MCP tool call it maps to.

    Only reads with an MCP equivalent are allowed; anything else fails loudly
    rather than silently degrading.
    """
    args = [a for a in args if a != "--json"]
    if len(args) >= 2 and args[0] == "db" and args[1] in ("pg", "fb", "es"):
        engine, flags = args[1], set(args[2:]) - {"-"}
        if flags - {"--highlight", "--pricing"}:
            raise _error(DataError, f"no MCP equivalent for tl {' '.join(args)}", 1)
        body = json.loads(input_text) if engine == "es" else input_text
        if engine == "es" and not isinstance(body, dict):
            raise _error(DataError, "ES query must be an object", 1)
        if engine != "es" and not isinstance(body, str):
            raise _error(DataError, "SQL query must be text", 1)
        # tl_db_es declares its query as a JSON *string* (the full DSL body).
        arguments = {"query": canonical(body) if engine == "es" else body,
                     "pricing": "--pricing" in flags}
        if engine == "es":
            arguments["include_highlight"] = "--highlight" in flags
        return {"tool": f"tl_db_{engine}", "arguments": arguments}
    if args == ["whoami"]:
        return {"tool": "tl_whoami", "arguments": {}}
    if (len(args) == 5 and args[:2] == ["channels", "similar"]
            and args[3] == "--limit"):
        return {"tool": "tl_channels_similar",
                "arguments": {"channel": args[2], "limit": int(args[4])}}
    raise _error(DataError, f"no MCP equivalent for tl {' '.join(args)}", 1)


def _bind(req: dict) -> tuple[Path, dict]:
    if req.get("tool") not in MCP_TOOLS:
        raise _error(DataError, f"unsupported MCP read: {req.get('tool')}", 1)
    session = Path(os.environ["TL_MCP_SESSION"]).resolve()
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    bound = {"contract": CONTRACT_VERSION, "session": meta["id"],
             "source": meta["source"], **req}
    return session, {"id": digest(bound), **bound}


def _receipt(req: dict):
    session, bound = _bind(req)
    target = session / "responses" / (bound["id"] + ".json")
    if not target.exists():
        return bound, None
    receipt = json.loads(target.read_text(encoding="utf-8"))
    if receipt.get("request") != bound or "response" not in receipt:
        raise _error(DataError, "receipt does not match the requested read", 1)
    return bound, receipt


def _mcp(req: dict) -> dict:
    bound, receipt = _receipt(req)
    if receipt is None:
        raise PendingRequest([bound])
    return normalize(receipt["response"])


_AUTH_CODES = {"unauthenticated", "unauthorized", "authentication_required",
               "auth_required"}
_TRANSIENT_CODES = {"internal_error", "upstream_error", "timeout", "rate_limited",
                    "service_unavailable"}


def normalize(value) -> dict:
    """Unwrap an MCP tool result to the CLI's JSON envelope; errors raise
    with the same exit-code classes as the CLI."""
    if not isinstance(value, dict):
        raise _error(DataError, "expected a JSON tool result object; missing "
                     "evidence is not an empty result", 1)
    transport_error = bool(value.get("isError"))
    if isinstance(value.get("structuredContent"), dict):
        value = value["structuredContent"]
    elif "content" in value and "results" not in value:
        blocks = value.get("content")
        if (not isinstance(blocks, list) or len(blocks) != 1
                or blocks[0].get("type") != "text"):
            raise _error(DataError, "expected one complete JSON tool result; "
                         "do not reconstruct partial text", 1)
        try:
            value = json.loads(blocks[0]["text"])
        except (ValueError, KeyError) as exc:
            if transport_error:
                raise _error(DataError, "MCP tool failed: "
                             + str(blocks[0].get("text", ""))[:1000], 3) from exc
            raise _error(DataError, "tool content is not complete JSON", 1) from exc
    if not isinstance(value, dict):
        raise _error(DataError, "tool payload must be an object", 1)
    if value.get("error") or (value.get("detail") and "results" not in value):
        code = str(value.get("code", ""))
        message = str(value.get("error") or value.get("detail"))
        if code in _AUTH_CODES:
            raise _error(CliUnavailable, "MCP connection not authenticated: " + message, 2)
        if "credit" in code:
            raise _error(CliUnavailable, "out of credits: " + message, 4)
        if any(s in code for s in ("premium", "quota", "seat", "forbidden",
                                   "permission", "access")):
            raise _error(CliUnavailable, "access denied (plan or permission): " + message, 5)
        if code in _TRANSIENT_CODES:
            raise _error(DataError, "rate-limited or server error (retryable): " + message, 3)
        raise _error(DataError, message, 1)
    if transport_error:
        raise _error(DataError, "MCP tool failed: " + canonical(value)[:1000], 3)
    return value


def query(engine: str, body, *, highlight: bool = False,
          timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a query and return the full envelope (totals, aggregations, rows).

    Withheld premium fields and quota truncation raise, like the row helpers;
    an envelope with no evidence at all is an error, not an empty result.
    """
    args = ["db", engine, "-", "--json"] + (["--highlight"] if highlight else [])
    data = _tl_json(args, input_text=json.dumps(body) if engine == "es" else body,
                    timeout=timeout)
    if not isinstance(data, dict):
        raise _error(DataError, f"tl db {engine} returned no result envelope", 1)
    _rows(data)                       # raises on withheld fields / truncation
    has_rows = any(isinstance(data.get(k), list) for k in ("results", "rows", "data"))
    has_aggs = isinstance(data.get("aggregations"), dict) and bool(data["aggregations"])
    if not (has_rows or has_aggs):
        raise _error(DataError, f"tl db {engine} response is missing evidence; "
                     "it is not a successful empty result", 1)
    return data


def prefetch(reads: list[tuple[str, object]]) -> None:
    """Request independent reads together in an MCP session (no-op on the CLI).

    ``reads`` is ``[(engine, body), ...]``; results are read later via query().
    """
    if not os.environ.get("TL_MCP_SESSION"):
        return
    pending: dict[str, dict] = {}
    for engine, body in reads:
        req = mcp_request(["db", engine, "-"],
                          json.dumps(body) if engine == "es" else body)
        bound, receipt = _receipt(req)
        if receipt is None:
            pending[bound["id"]] = bound
        if len(pending) == PREFETCH_LIMIT:
            break
    if pending:
        raise PendingRequest(list(pending.values()))


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "preflight":
        preflight()
        print("OK")
    else:
        sys.exit("usage: tl_data.py preflight")
