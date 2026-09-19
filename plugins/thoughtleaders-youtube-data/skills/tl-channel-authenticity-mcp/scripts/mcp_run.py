#!/usr/bin/env python3
"""Run shared processing scripts with connected-tool evidence, without tl.

run emits pending tool requests or the path to completed output. ingest stores
an exact tool response for a pending request. Repeat run with the same inputs.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import runpy
import sys
import time
import uuid
from pathlib import Path

import tl_data


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def source_hash(directory: Path) -> str:
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob("*.py"))}
    files["shared/tl_data.py"] = hashlib.sha256(Path(tl_data.__file__).read_bytes()).hexdigest()
    files["shared/mcp_run.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return tl_data.digest(files)


def session_meta(session: Path, source: str | None = None) -> dict:
    path = session / "session.json"
    if not path.exists():
        if source is None:
            raise tl_data.DataError("Start run before importing responses")
        session.mkdir(parents=True, exist_ok=True, mode=0o700)
        if any(session.iterdir()):
            raise tl_data.DataError("New session needs an empty directory")
        metadata = {"id": str(uuid.uuid4()), "source": source, "created": time.time(),
                    "local_date": datetime.date.today().isoformat(), "contract": tl_data.CONTRACT_VERSION}
        write(path, metadata)
        (session / "responses").mkdir()
        write(session / "requests.json", {})
    metadata = read(path)
    if metadata.get("contract") != tl_data.CONTRACT_VERSION or (source is not None and source != metadata.get("source")):
        raise tl_data.DataError("Skill code changed. Start a new evidence session")
    # A midnight boundary can change date-based queries on replay. Do not mix
    # new cutoffs with yesterday's evidence or silently extend stale sessions.
    if metadata.get("local_date") != datetime.date.today().isoformat() or time.time() - metadata["created"] > 86400:
        raise tl_data.DataError("Evidence session expired. Start a new session")
    return metadata


def ingest(session: Path, request_id: str, response_path: Path) -> dict:
    session_meta(session)
    requests = read(session / "requests.json")
    if request_id not in requests:
        raise tl_data.DataError("Unknown request ID; use an emitted pending request")
    req = requests[request_id]
    if req["id"] != tl_data.digest({k: v for k, v in req.items() if k != "id"}):
        raise tl_data.DataError("Pending request digest mismatch")
    response = read(response_path)
    if not isinstance(response, dict):
        raise tl_data.DataError("Response file must contain the exact JSON tool result object")
    target = session / "responses" / (request_id + ".json")
    receipt = {"request": req, "response": response}
    # Never overwrite earlier evidence. Error receipts are retained too; the
    # processing stage reports the failure instead of retrying paid queries.
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False)
    except FileExistsError as exc:
        raise tl_data.DataError("Response already recorded for this request") from exc
    return {"phase": "recorded", "request_id": request_id}


def retry(session: Path, request_id: str) -> dict:
    """Explicitly retry transient reads, retaining at most two failed attempts."""
    session_meta(session)
    requests = read(session / "requests.json")
    if request_id not in requests:
        raise tl_data.DataError("Unknown request ID")
    path = session / "responses" / (request_id + ".json")
    receipt = read(path)
    if receipt.get("request") != requests[request_id]:
        raise tl_data.DataError("Receipt request mismatch")
    try:
        tl_data.normalize(receipt["response"])
    except tl_data.DataError as exc:
        if exc.exit_code != 3:
            raise tl_data.DataError("Only transient tool failures can be retried; resolve access/evidence errors first") from exc
    else:
        raise tl_data.DataError("Successful evidence cannot be replaced")
    attempts = session / "failed-attempts"
    attempts.mkdir(exist_ok=True)
    previous = list(attempts.glob(request_id + ".*.json"))
    if len(previous) >= 2:
        raise tl_data.DataError("Retry limit reached for this request")
    path.rename(attempts / (request_id + f".{len(previous) + 1}.json"))
    # Some processors deliberately emit partial results for failed candidates.
    # Keep evidence intact but recompute derived stdout after a retry succeeds.
    for output in session.glob("*.output.txt"):
        output.unlink()
    return {"phase": "needs_tools", "requests": [requests[request_id]], "retry": len(previous) + 1}


def run(session: Path, script: Path, arguments: list[str], input_path: Path | None = None) -> dict:
    if not script.is_file() or script.suffix != ".py":
        raise tl_data.DataError("Expected a packaged Python processing script")
    metadata = session_meta(session, source_hash(script.parent))
    input_text = input_path.read_text(encoding="utf-8") if input_path else ""
    input_files = {}
    for argument in arguments:
        candidate = Path(argument)
        if candidate.is_file():
            input_files[str(candidate.resolve())] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    invocation = tl_data.digest({"script": script.name, "args": arguments, "stdin": input_text, "files": input_files})
    output_path = session / (invocation + ".output.txt")
    if output_path.exists():
        return {"phase": "complete", "output_path": str(output_path), "reused": True}
    output = io.StringIO()
    old_argv, old_stdin, old_path = sys.argv, sys.stdin, list(sys.path)
    old_session = os.environ.get("TL_MCP_SESSION")
    try:
        os.environ["TL_MCP_SESSION"] = str(session)
        sys.argv = [str(script), *arguments]
        sys.stdin = io.StringIO(input_text)
        sys.path.insert(0, str(script.parent))
        with contextlib.redirect_stdout(output):
            # Establish caller context before any data query, cached per run.
            tl_data.preflight()
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise tl_data.DataError("Processing script failed: " + output.getvalue(), int(exc.code) if isinstance(exc.code, int) else 1) from exc
    except tl_data.PendingRequest as pending:
        requests = read(session / "requests.json")
        for req in pending.requests:
            if req["session"] != metadata["id"]:
                raise tl_data.DataError("Request belongs to another session")
            requests[req["id"]] = req
        write(session / "requests.json", requests)
        return {"phase": "needs_tools", "requests": pending.requests,
                "instruction": "Call each connected tool with these arguments. Save each exact JSON result and ingest it by request ID, then repeat this run. Keep the same connected account."}
    finally:
        sys.argv, sys.stdin, sys.path = old_argv, old_stdin, old_path
        if old_session is None:
            os.environ.pop("TL_MCP_SESSION", None)
        else:
            os.environ["TL_MCP_SESSION"] = old_session
    output_path.write_text(output.getvalue(), encoding="utf-8")
    return {"phase": "complete", "output_path": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--session", type=Path, required=True)
    run_parser.add_argument("--input", type=Path)
    run_parser.add_argument("script", type=Path)
    run_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument("--session", type=Path, required=True)
    ingest_parser.add_argument("--request", required=True)
    ingest_parser.add_argument("--response", type=Path, required=True)
    retry_parser = sub.add_parser("retry")
    retry_parser.add_argument("--session", type=Path, required=True)
    retry_parser.add_argument("--request", required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            result = run(args.session.resolve(), args.script.resolve(), args.arguments, args.input)
        elif args.command == "ingest":
            result = ingest(args.session.resolve(), args.request, args.response)
        else:
            result = retry(args.session.resolve(), args.request)
        print(json.dumps(result, ensure_ascii=False))
    except (tl_data.DataError, ValueError, OSError) as exc:
        print(json.dumps({"phase": "error", "message": str(exc)}))
        sys.exit(getattr(exc, "exit_code", 1))


if __name__ == "__main__":
    main()
