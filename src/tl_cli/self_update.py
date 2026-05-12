"""Post-command version check and auto-upgrade for pipx/uv installs.

Runs once per CLI invocation via atexit. Skipped for dev / pip installs
(we only know how to upgrade pipx and `uv tool` installations cleanly).

Network fetches are cached for 1 hour in ~/.cache/tl-cli/version-check.json,
so repeated invocations don't hammer the GitHub API.

All failure paths are silent — version-check issues must never break the
user's actual command output.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from tl_cli import __version__

CACHE_PATH = Path.home() / ".cache" / "tl-cli" / "version-check.json"
CACHE_TTL_SECONDS = 3600  # 1 hour
LATEST_URL = "https://api.github.com/repos/ThoughtLeaders-io/thoughtleaders-cli/releases/latest"
REQUEST_TIMEOUT = 2  # tight — the user is already waiting to see their shell prompt back


def _detect_install_method() -> str | None:
    """Return 'pipx', 'uv', or None (dev/pip install — don't auto-upgrade).

    Both the new distribution name (`thoughtleaders-cli`) and the legacy one
    (`tl-cli`) are matched so users who installed before the rename keep
    auto-updating. `Path.as_posix()` normalises Windows backslashes so the
    same substring checks work on every platform.
    """
    exe = Path(sys.executable).as_posix()
    for dist_name in ("thoughtleaders-cli", "tl-cli"):
        if f"/pipx/venvs/{dist_name}/" in exe:
            return "pipx"
        if f"/uv/tools/{dist_name}/" in exe:
            return "uv"
    return None


def _read_cache() -> dict | None:
    try:
        cache = json.loads(CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - cache.get("checked_at", 0) >= CACHE_TTL_SECONDS:
        return None
    return cache


def _write_cache(latest: str | None) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"checked_at": time.time(), "latest": latest}))
    except OSError as e:
        print(f"Error writing cache: {e}", file=sys.stderr)
        pass


def _fetch_latest_version() -> str | None:
    """Fetch latest release tag from GitHub. Returns the plain version
    string (e.g. '0.4.2') or None on any failure."""
    try:
        req = urllib.request.Request(
            LATEST_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"tl-cli/{__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    tag = (data.get("tag_name") or "").lstrip("v")
    return tag or None


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split(".") if p.isdigit())


REPO_URL = "https://github.com/ThoughtLeaders-io/thoughtleaders-cli.git"


def _run_upgrade(method: str, latest: str) -> None:
    """Block briefly to run the upgrade. Progress goes to stderr so piped
    stdout stays clean.

    Uses `install --force` with the new tag URL. pipx/uv pin the original
    install spec including the git tag, so a plain `upgrade` re-installs
    the same version — `--force` is the only way to advance the pinned tag.

    On a successful upgrade, re-syncs Claude Code and OpenCode skills if
    their respective binaries are on PATH, so the new version's skills
    land in ~/.claude/ and ~/.config/opencode/ without the user having
    to remember to run `tl setup ...`.
    """
    tagged_url = f"git+{REPO_URL}@v{latest}"
    cmd = {
        "pipx": ["pipx", "install", "--force", tagged_url],
        "uv": ["uv", "tool", "install", "--force", tagged_url],
    }.get(method)
    if not cmd:
        return
    print(
        f"[tl-cli] upgrading {__version__} → {latest} via {method}…",
        file=sys.stderr,
    )
    # Capture output so a noisy traceback from a broken upgrader (seen on
    # Windows pipx shims that lose track of their own module) doesn't get
    # dumped into the user's shell — we surface it deliberately on failure
    # alongside an actionable next-step message.
    try:
        result = subprocess.run(cmd, check=False, timeout=60, capture_output=True, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            f"[tl-cli] could not run {method}: {exc}\n"
            f"[tl-cli] upgrade manually with:\n  {' '.join(cmd)}",
            file=sys.stderr,
        )
        return
    if result.returncode == 0:
        _resync_integrations()
        return
    _report_upgrade_failure(method, cmd, result)


def _report_upgrade_failure(method: str, cmd: list[str], result: subprocess.CompletedProcess) -> None:
    """Print a user-friendly failure message after a non-zero upgrader exit.

    On Windows in particular, `pipx.exe` can be a broken shim that errors
    with `ModuleNotFoundError: No module named 'pipx'`. We detect that and
    give a targeted hint instead of just echoing the traceback.
    """
    combined_err = (result.stderr or '') + (result.stdout or '')
    print(
        f"[tl-cli] automatic upgrade failed (exit {result.returncode}).",
        file=sys.stderr,
    )
    if "No module named 'pipx'" in combined_err:
        print(
            "[tl-cli] Your pipx install appears broken (its launcher can't find the pipx module).\n"
            "[tl-cli] Reinstall pipx from your system Python, then rerun the upgrade.\n"
            "[tl-cli] Or switch to uv:  uv tool install --force " + cmd[-1],
            file=sys.stderr,
        )
    else:
        print(
            f"[tl-cli] To upgrade manually, run:\n  {' '.join(cmd)}",
            file=sys.stderr,
        )
    if combined_err.strip():
        print("[tl-cli] Upgrader output:", file=sys.stderr)
        sys.stderr.write(combined_err if combined_err.endswith('\n') else combined_err + '\n')


def _resync_integrations() -> None:
    """Re-sync Claude Code and OpenCode skills after a self-upgrade.

    Spawned as a subprocess against the freshly-installed `tl` binary —
    the running process holds the OLD code in memory, so calling the
    setup functions in-process would (depending on import caching) copy
    the wrong assets. Subprocess re-execs the new code from disk.

    Conditional on each tool's binary being on PATH; everything is
    silent on failure (a skill resync issue must never fail the
    upgrade itself).
    """
    tl_bin = shutil.which("tl")
    if not tl_bin:
        return
    for tool, binary in (("claude", "claude"), ("opencode", "opencode")):
        if not shutil.which(binary):
            continue
        print(f"[tl-cli] re-syncing {tool} skills…", file=sys.stderr)
        try:
            subprocess.run(
                [tl_bin, "setup", tool, "--json"],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def check_and_upgrade() -> None:
    """Entry point. Runs via atexit; silent on every failure path."""
    try:
        method = _detect_install_method()
        if not method:
            return

        cache = _read_cache()
        if cache is None:
            latest = _fetch_latest_version()
            _write_cache(latest)
        else:
            latest = cache.get("latest")

        if not latest:
            return
        try:
            if _version_tuple(latest) <= _version_tuple(__version__):
                return
        except ValueError:
            return

        _run_upgrade(method, latest)
    except Exception:
        # Never let a version-check bug break the user's workflow.
        pass


def force_upgrade() -> None:
    """Explicitly requested upgrade — bypasses cache, prints verbose output."""
    method = _detect_install_method()
    if not method:
        print(
            "tl-cli was not installed via pipx or uv — cannot auto-upgrade.\n"
            "Update it with the same tool you used to install it.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Checking for updates (current: {__version__})…", file=sys.stderr)
    latest = _fetch_latest_version()
    if latest is None:
        print("Could not reach GitHub to check for updates.", file=sys.stderr)
        sys.exit(1)

    _write_cache(latest)

    try:
        newer = _version_tuple(latest) > _version_tuple(__version__)
    except ValueError:
        newer = False

    if not newer:
        print(f"tl-cli {__version__} is already the latest version.", file=sys.stderr)
        return

    _run_upgrade(method, latest)
