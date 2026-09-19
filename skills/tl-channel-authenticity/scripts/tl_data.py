"""Shared read operations for CLI execution and explicit MCP evidence sessions.

The full-envelope query interface preserves metadata. Row helpers retain the
creator-brief seam's interface. MCP credentials stay with the connected host.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

CONTRACT_VERSION = 1
DEFAULT_TIMEOUT = 180


class DataError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class CliUnavailable(DataError):
    pass


class PendingRequest(BaseException):
    """Suspend processing without converting missing evidence into a result."""

    def __init__(self, requests: list[dict]):
        self.requests = requests


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def normalize(value) -> dict:
    """Unwrap MCP transport content, retaining the complete data envelope."""
    if not isinstance(value, dict):
        raise DataError("Expected a JSON result object; missing evidence is not an empty result")
    transport_error = bool(value.get("isError"))
    if isinstance(value.get("structuredContent"), dict):
        value = value["structuredContent"]
    elif "content" in value and "results" not in value:
        blocks = value.get("content")
        if not isinstance(blocks, list) or len(blocks) != 1 or blocks[0].get("type") != "text":
            raise DataError("Expected one complete JSON tool result; do not reconstruct partial text")
        try:
            value = json.loads(blocks[0]["text"])
        except (ValueError, KeyError) as exc:
            if transport_error:
                raise DataError("MCP tool failed: " + str(blocks[0].get("text", ""))[:1000], 3) from exc
            raise DataError("Tool content is not complete JSON") from exc
    if not isinstance(value, dict):
        raise DataError("Tool payload must be an object")
    if value.get("error") or (value.get("detail") and "results" not in value):
        code = str(value.get("code", ""))
        exit_code = 2 if code in {"unauthenticated", "unauthorized", "authentication_required", "auth_required"} else (
            4 if "credit" in code else 5 if any(s in code for s in ("premium", "quota", "seat", "forbidden", "permission", "access")) else
            3 if code in {"internal_error", "upstream_error", "timeout", "rate_limited", "service_unavailable"} else 1
        )
        raise DataError(str(value.get("error") or value.get("detail")), exit_code)
    if transport_error:
        raise DataError("MCP tool failed: " + canonical(value), 3)
    if value.get("_upgrade_required") or value.get("quota_notice"):
        raise DataError("Required evidence was withheld or truncated: " + canonical(value.get("_upgrade_required") or value["quota_notice"]), 5)
    return value


def rows(value) -> list[dict]:
    if isinstance(value, list):
        return value
    data = normalize(value)
    for key in ("results", "rows", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    raise DataError("Result did not include a row list")


def _cli(args: list[str], *, input_text: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        result = subprocess.run(
            [os.environ.get("TL_CLI_BIN", "tl"), *args], input=input_text,
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CliUnavailable("tl CLI unavailable. Run tl auth login after installing the CLI.", 2) from exc
    except subprocess.TimeoutExpired as exc:
        raise DataError(f"Query timed out after {timeout}s", 3) from exc
    if result.returncode:
        error = (result.stderr or result.stdout or "Query failed").strip()
        cls = CliUnavailable if result.returncode in (2, 4, 5) else DataError
        raise cls(error, result.returncode)
    try:
        return normalize(json.loads(result.stdout))
    except ValueError as exc:
        raise DataError("Query returned invalid JSON") from exc


def request(operation: str, arguments: dict) -> dict:
    allowed = {"tl_db_pg", "tl_db_fb", "tl_db_es", "tl_whoami", "tl_channels_similar"}
    if operation not in allowed:
        raise DataError("Unsupported shared read operation: " + operation)
    return {"tool": operation, "arguments": arguments}


def session_request(req: dict) -> tuple[Path, dict]:
    session = Path(os.environ["TL_MCP_SESSION"]).resolve()
    metadata = json.loads((session / "session.json").read_text(encoding="utf-8"))
    bound = {"contract": CONTRACT_VERSION, "session": metadata["id"], "source": metadata["source"], **req}
    return session, {"id": digest(bound), **bound}


def _receipt(req: dict):
    session, bound = session_request(req)
    target = session / "responses" / (bound["id"] + ".json")
    if not target.exists():
        return bound, None
    receipt = json.loads(target.read_text(encoding="utf-8"))
    if receipt.get("request") != bound or "response" not in receipt:
        raise DataError("Receipt does not match the requested operation")
    return bound, receipt


def _mcp(req: dict) -> dict:
    bound, receipt = _receipt(req)
    if receipt is None:
        raise PendingRequest([bound])
    return normalize(receipt["response"])


def _query_request(engine: str, body, include_highlight: bool = False, pricing: bool = False) -> dict:
    if engine not in {"pg", "fb", "es"}:
        raise DataError("Unknown query engine")
    if engine == "es" and not isinstance(body, dict):
        raise DataError("ES query must be an object")
    if engine != "es" and not isinstance(body, str):
        raise DataError("SQL query must be text")
    arguments = {"query": body, "pricing": pricing}
    if engine == "es":
        arguments["include_highlight"] = include_highlight
    return request("tl_db_" + engine, arguments)


def query(engine: str, body, *, include_highlight: bool = False, pricing: bool = False, timeout: int = DEFAULT_TIMEOUT) -> dict:
    req = _query_request(engine, body, include_highlight, pricing)
    if os.environ.get("TL_MCP_SESSION"):
        result = _mcp(req)
    else:
        args = ["db", engine, "-", "--json"]
        if include_highlight:
            args.append("--highlight")
        if pricing:
            args.append("--pricing")
        result = _cli(args, input_text=json.dumps(body) if engine == "es" else body, timeout=timeout)
    if not pricing:
        has_rows = any(isinstance(result.get(key), list) for key in ("results", "rows", "data"))
        has_hits = engine == "es" and isinstance(result.get("hits"), dict) and isinstance(result["hits"].get("hits"), list)
        has_aggs = engine == "es" and isinstance(result.get("aggregations"), dict) and bool(result["aggregations"])
        if not (has_rows or has_hits or has_aggs):
            raise DataError("Query response is missing evidence; it is not a successful empty result", 5)
    return result


def prefetch(requests: list[dict]) -> None:
    """Prepare independent reads together; defer interpretation to query()."""
    if not os.environ.get("TL_MCP_SESSION"):
        return
    pending = {}
    for item in requests:
        req = _query_request(item["engine"], item["query"], item.get("include_highlight", False), item.get("pricing", False))
        bound, receipt = _receipt(req)
        if receipt is None:
            pending[bound["id"]] = bound
        if len(pending) == 100:
            break
    if pending:
        raise PendingRequest(list(pending.values()))


def db_pg(sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return rows(query("pg", sql, timeout=timeout))


def db_fb(sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return rows(query("fb", sql, timeout=timeout))


def db_es(body: dict, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return rows(query("es", body, timeout=timeout))


def whoami(*, timeout: int = 60) -> dict:
    if os.environ.get("TL_MCP_SESSION"):
        return _mcp(request("tl_whoami", {}))
    return _cli(["whoami", "--json"], timeout=timeout)


def preflight() -> None:
    whoami()


def channels_similar(channel_id: int, limit: int = 20) -> list[dict]:
    if os.environ.get("TL_MCP_SESSION"):
        return rows(_mcp(request("tl_channels_similar", {"channel": str(channel_id), "limit": limit})))
    return rows(_cli(["channels", "similar", str(channel_id), "--limit", str(limit), "--json"]))
