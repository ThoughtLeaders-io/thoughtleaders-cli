"""Local bookkeeping for downloaded skills: registry, install marker, path
safety, and atomic install.

Three files this module owns:

- ``~/.config/tl/skills.json`` — the registry of every skill `tl skill
  download` has installed, and where.
- ``.tl-skill.json`` — written inside each installed skill directory so a
  later run can tell "this directory is ours" apart from a user's own
  skill of the same name. `tl setup` / `tl update`'s cleanup routines are
  expected to import ``is_marked_for`` so they never touch a marker-bearing
  directory (see module docstring note at the bottom).
- ``~/.config/tl/skills-check.json`` — a 24h cache for the per-run
  staleness check in ``tl_cli.commands.skills``.

Kept separate from ``tl_cli/commands/skills.py`` (the Typer app) so the
install/registry primitives have no dependency on the HTTP client or Typer —
that keeps them trivially importable from `tl_cli/commands/setup.py` and
`tl_cli/self_update.py`, whose cleanup routines need `is_marked_for` to skip
directories `tl skill download` manages (tracked as follow-up work; not part
of this change).
"""

import json
import ntpath
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from tl_cli.config import CONFIG_DIR

REGISTRY_PATH = CONFIG_DIR / "skills.json"
MARKER_FILENAME = ".tl-skill.json"
STALENESS_CACHE_PATH = CONFIG_DIR / "skills-check.json"
STALENESS_TTL_SECONDS = 24 * 3600
# Backoff window after a *failed* staleness check (unreachable/slow server):
# much shorter than the 24h success TTL, so the network gets retried again
# reasonably soon, but not on literally every single `tl` invocation.
STALENESS_FAILURE_TTL_SECONDS = 3600

SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SKILL_NAME_MAX_LENGTH = 64


class PathSafetyError(ValueError):
    """A server-supplied relative file path failed safety validation."""


class InvalidSkillNameError(ValueError):
    """A user-typed skill name doesn't match the allowed name shape."""


def validate_skill_name(name: str) -> None:
    """Raise `InvalidSkillNameError` unless `name` is a safe skill identifier.

    Checked before any network call or path construction: `download`/`update`
    build `target_root / name` directly from this value, so a name shaped
    like a path (e.g. containing `/`, `..`, or backslashes) must never reach
    that join.
    """
    if not isinstance(name, str) or len(name) > SKILL_NAME_MAX_LENGTH or not SKILL_NAME_RE.match(name):
        raise InvalidSkillNameError(
            f"invalid skill name: {name!r} — expected lowercase letters, digits, and hyphens "
            f"(starting with a letter or digit), {SKILL_NAME_MAX_LENGTH} characters or fewer"
        )


# --- Path safety -------------------------------------------------------


def validate_relpath(relpath: str) -> None:
    """Raise `PathSafetyError` unless `relpath` is a safe relative POSIX path.

    Defense in depth: the server validates the same rules before a skill
    bundle is ever stored, but a client-side check costs nothing and
    protects against a compromised or buggy server response before a
    single byte is written to disk.
    """
    if not isinstance(relpath, str) or not relpath:
        raise PathSafetyError(f"empty or non-string file path: {relpath!r}")
    if "\\" in relpath:
        raise PathSafetyError(f"backslash not allowed in path: {relpath!r}")
    if "\x00" in relpath:
        raise PathSafetyError(f"NUL byte not allowed in path: {relpath!r}")
    if relpath.startswith("/"):
        raise PathSafetyError(f"absolute path not allowed: {relpath!r}")
    # A Windows drive-qualified path ('C:/x', 'C:x') is absolute on Windows, so
    # joining it to the install directory would discard that directory. This is
    # pure string logic and is correct regardless of the host OS.
    if ntpath.splitdrive(relpath)[0]:
        raise PathSafetyError(f"drive-qualified path not allowed: {relpath!r}")
    for segment in relpath.split("/"):
        if segment in ("", ".", ".."):
            raise PathSafetyError(f"unsafe path segment in {relpath!r}")


def validate_files(files: dict[str, str]) -> None:
    """Validate every path in a `{relpath: content}` skill bundle upfront.

    Called before any target directory is touched, so a single bad path
    aborts the whole install rather than leaving some targets written and
    others not.
    """
    for relpath, content in files.items():
        validate_relpath(relpath)
        if not isinstance(content, str):
            raise PathSafetyError(f"file content for {relpath!r} must be text")


def _resolve_within(target_dir: Path, relpath: str) -> Path:
    """Resolve `relpath` under `target_dir`, asserting containment.

    Second, independent check (path-resolution-based rather than
    string-based) applied at write time as the ultimate safety net.
    """
    validate_relpath(relpath)
    dest = (target_dir / relpath).resolve()
    if not dest.is_relative_to(target_dir.resolve()):
        raise PathSafetyError(f"path escapes target directory: {relpath!r}")
    return dest


# --- Marker --------------------------------------------------------------


def read_marker(path: Path) -> dict | None:
    """Read and validate `.tl-skill.json` in `path`. None if absent/invalid."""
    marker_path = path / MARKER_FILENAME
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not all(isinstance(data.get(k), str) for k in ("name", "version", "checksum", "managed_by")):
        return None
    return data


def is_marked_for(path: Path, name: str) -> bool:
    """True if `path` is a directory carrying a valid tl-managed marker for `name`.

    This is the safety predicate every mutation in this module (and, per
    the module docstring, `tl setup` / `tl update`'s cleanup routines)
    must check before touching an existing directory: unmarked dirs are
    never assumed to be ours.
    """
    if not path.is_dir():
        return False
    marker = read_marker(path)
    return marker is not None and marker.get("managed_by") == "tl" and marker.get("name") == name


def write_marker(path: Path, *, name: str, version: str, checksum: str) -> None:
    marker = {"name": name, "version": version, "checksum": checksum, "managed_by": "tl"}
    (path / MARKER_FILENAME).write_text(json.dumps(marker), encoding="utf-8")


# --- Atomic install --------------------------------------------------------


def install_skill_tree(
    files: dict[str, str],
    target_dir: Path,
    *,
    name: str,
    version: str,
    checksum: str,
) -> None:
    """Atomically write `files` (relpath -> text) into `target_dir`.

    Writes the whole tree to a sibling temp directory first (same
    filesystem, so the final rename is atomic), adds the `.tl-skill.json`
    marker, then swaps: any existing `target_dir` is moved aside, the temp
    directory takes its place, and the old one is deleted. On any failure
    the temp directory is cleaned up and `target_dir` is left exactly as
    it was — nothing partially written.

    Callers are expected to have already run `validate_files` on the whole
    bundle; the per-file `_resolve_within` check here is a second,
    independent safety net, not the primary gate.
    """
    parent = target_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = parent / f".{name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        tmp_dir.mkdir(parents=True)
        for relpath, content in files.items():
            dest = _resolve_within(tmp_dir, relpath)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        write_marker(tmp_dir, name=name, version=version, checksum=checksum)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    old_dir = parent / f".{name}.old-{uuid.uuid4().hex[:8]}"
    moved_old = False
    if target_dir.exists():
        target_dir.rename(old_dir)
        moved_old = True
    try:
        tmp_dir.rename(target_dir)
    except Exception:
        if moved_old:
            old_dir.rename(target_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    if moved_old:
        shutil.rmtree(old_dir, ignore_errors=True)


# --- Atomic JSON write -----------------------------------------------------


def _atomic_write_json(path: Path, data: dict, *, indent: int | None = None) -> None:
    """Write `data` as JSON to `path` via a temp file + `os.replace`.

    Serialization happens before any file is touched, so a bad `data` (e.g.
    non-serializable content) raises without disturbing `path`. The payload
    is then written to a sibling temp file and swapped in with `os.replace`
    — atomic on the same filesystem — so a crash mid-write can never leave
    `path` half-written; the previous content survives untouched until the
    swap succeeds.
    """
    payload = json.dumps(data, indent=indent)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


# --- Registry --------------------------------------------------------------


def read_registry() -> dict:
    """Read `skills.json`, tolerating a missing or corrupt file."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"skills": {}}
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        return {"skills": {}}
    return data


def write_registry(data: dict) -> None:
    _atomic_write_json(REGISTRY_PATH, data, indent=2)


# --- Staleness cache ---------------------------------------------------


def read_staleness_cache() -> dict | None:
    """Return the cached `/skills/versions/` outcome, success or failure.

    A successful check is cached for `STALENESS_TTL_SECONDS` (24h) and
    returns the cached `results` dict. A *failed* check (network error,
    unreachable/slow server) is cached for the much shorter
    `STALENESS_FAILURE_TTL_SECONDS` backoff window and returned as
    `{"checked_at": ..., "failed": True}` — callers must check `failed`
    before touching `results`. Returns None once either window has
    expired, or the file is missing/corrupt/malshaped.
    """
    try:
        cache = json.loads(STALENESS_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(cache, dict):
        return None
    checked_at = cache.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return None

    if cache.get("failed"):
        if time.time() - checked_at >= STALENESS_FAILURE_TTL_SECONDS:
            return None
        return cache

    if time.time() - checked_at >= STALENESS_TTL_SECONDS:
        return None
    if not isinstance(cache.get("results"), dict):
        return None
    return cache


def write_staleness_cache(results: dict) -> None:
    try:
        _atomic_write_json(STALENESS_CACHE_PATH, {"checked_at": time.time(), "results": results})
    except OSError:
        pass


def write_staleness_failure() -> None:
    """Record a failed staleness check so the next run backs off the network.

    Called instead of `write_staleness_cache` when the `/skills/versions/`
    call itself fails — writing this stamp is what makes subsequent `tl`
    invocations skip the network (and its timeout) for
    `STALENESS_FAILURE_TTL_SECONDS`, instead of retrying on every run.
    """
    try:
        _atomic_write_json(STALENESS_CACHE_PATH, {"checked_at": time.time(), "failed": True})
    except OSError:
        pass
