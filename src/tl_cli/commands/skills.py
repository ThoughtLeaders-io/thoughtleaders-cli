"""tl skill — Download, list, update, and remove server-distributed skills.

Distinct from the bundled skill set `tl setup claude|opencode|gemini|codex`
installs: these are skills an organization has been granted access to on
the server, fetched and installed on demand.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.commands.setup import AGENTS_SKILLS_DIR, CLAUDE_SKILLS_DIR, OPENCODE_SKILLS_DIR
from tl_cli.output.formatter import detect_format, output
from tl_cli.skill_registry import (
    InvalidSkillNameError,
    PathSafetyError,
    install_skill_tree,
    is_marked_for,
    read_registry,
    read_staleness_cache,
    validate_files,
    validate_skill_name,
    write_registry,
    write_staleness_cache,
    write_staleness_failure,
)

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Download, list, update, and remove distributed skills")
console = Console(stderr=True)

COLUMNS = ["name", "latest_version", "installed_version", "status", "description"]

# Kept well under the client's default 30s timeout: this call runs on every
# `tl` invocation in the background, so a hung/slow server should fail fast
# rather than stall the user's actual command for up to 30s.
STALENESS_CHECK_TIMEOUT_SECONDS = 5.0


def _install_targets() -> list[Path]:
    """Every skill-directory root a downloaded skill installs into.

    Mirrors the harness targets `tl setup` uses for the bundled skill set:
    Claude Code's standalone skills directory (the plugin/marketplace
    channel only ships the bundled set via GitHub releases and can't
    deliver a single downloaded skill on its own), OpenCode's skills
    directory, and the directory shared by Gemini and Codex. Reused
    directly from `tl_cli.commands.setup` rather than duplicated here.
    """
    return [CLAUDE_SKILLS_DIR, OPENCODE_SKILLS_DIR, AGENTS_SKILLS_DIR]


def _truncate(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _install_one(
    dest: Path,
    *,
    name: str,
    version: str,
    checksum: str,
    files: dict[str, str],
    force: bool,
) -> dict:
    """Install a skill tree into a single target directory.

    A destination that already exists and carries our marker for `name` is
    always replaced. A destination that exists without our marker is
    refused unless `force` is set.
    """
    if dest.exists() and not is_marked_for(dest, name):
        if not force:
            return {
                "path": str(dest),
                "installed": False,
                "action": "refused",
                "reason": "already exists and is not managed by tl (use --force to overwrite)",
            }
        action = "overwritten"
    elif dest.exists():
        action = "replaced"
    else:
        action = "installed"

    install_skill_tree(files, dest, name=name, version=version, checksum=checksum)
    return {"path": str(dest), "installed": True, "action": action}


def _fetch_skill(name: str) -> dict:
    """GET /skills/<name>/ and return its `results` block."""
    client = get_client()
    try:
        data = client.get(f"/skills/{name}/")
    finally:
        client.close()
    return data.get("results", data)


def _download_and_install(name: str, *, force: bool) -> dict:
    """Fetch a skill and install it to every target directory.

    Shared by `tl skill download` and `tl skill update` — `update` always
    passes `force=False`: a directory that already carries our marker for
    this skill is replaced regardless of `force`, so the flag only matters
    for a directory `tl` doesn't recognize as its own, which `update`
    should never silently clobber.
    """
    validate_skill_name(name)
    result = _fetch_skill(name)
    version = result["version"]
    checksum = result["checksum"]
    files = result["files"]

    validate_files(files)

    targets: list[dict] = []
    installed_count = 0
    for target_root in _install_targets():
        dest = target_root / name
        outcome = _install_one(dest, name=name, version=version, checksum=checksum, files=files, force=force)
        targets.append(outcome)
        if outcome["installed"]:
            installed_count += 1

    if installed_count:
        registry = read_registry()
        registry.setdefault("skills", {})[name] = {
            "version": version,
            "checksum": checksum,
            "paths": [t["path"] for t in targets if t["installed"]],
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        write_registry(registry)

    return {
        "name": name,
        "version": version,
        "checksum": checksum,
        "targets": targets,
        "installed_count": installed_count,
    }


def check_skill_staleness() -> str | None:
    """Per-run staleness nag for downloaded skills.

    Entirely best-effort: any failure (empty registry, no auth, network
    down, corrupt cache, server error) silently returns None — this must
    never break or slow down normal CLI usage. Only hits the network when
    the cache is empty or older than 24h; otherwise reuses the cached
    result. A *failed* network call is itself cached for a short backoff
    window (`STALENESS_FAILURE_TTL_SECONDS`) so an unreachable/slow server
    doesn't force a retry — and its accompanying httpx timeout — on every
    single `tl` invocation; a success later overwrites that stamp and
    resumes the normal 24h cache. Returns at most one short line naming
    every skill that has drifted from its latest available version, or
    None when nothing has (or the check was skipped/failed).
    """
    try:
        registry = read_registry()
        installed = registry.get("skills", {})
        if not installed:
            return None

        cache = read_staleness_cache()
        if cache is not None:
            if cache.get("failed"):
                return None
            results = cache["results"]
        else:
            client = get_client()
            try:
                names = ",".join(sorted(installed.keys()))
                data = client.get("/skills/versions/", params={"names": names}, timeout=STALENESS_CHECK_TIMEOUT_SECONDS)
            except Exception:
                write_staleness_failure()
                return None
            finally:
                client.close()
            results = data.get("results", {})
            write_staleness_cache(results)

        outdated = sorted(name for name, info in installed.items() if results.get(name) and results.get(name) != info.get("version"))
        if not outdated:
            return None
        return f"{len(outdated)} skill(s) outdated ({', '.join(outdated)}) — run `tl skill update`"
    except Exception:
        return None


# --- Typer app -------------------------------------------------------------


@app.callback(invoke_without_command=True)
def skill(ctx: typer.Context) -> None:
    """Download, list, update, and remove skills distributed to your organization."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd, all_=False, json_output=False, csv_output=False, md_output=False, toon_output=False)


@app.command("list")
def list_cmd(
    all_: bool = typer.Option(False, "--all", help="List the full catalog (full-access accounts only)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """List skills available to your organization (free).

    Examples:
        tl skill list
        tl skill list --all      # full catalog (full-access accounts only)
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    client = get_client()
    try:
        params = {"all": "1"} if all_ else None
        data = client.get("/skills/", params=params)
    except ApiError as e:
        handle_api_error(e)
        return
    finally:
        client.close()

    registry = read_registry()
    installed = registry.get("skills", {})

    rows = []
    for item in data.get("results", []):
        name = item.get("name")
        latest = item.get("version")
        inst = installed.get(name)
        installed_version = inst["version"] if inst else None
        outdated = bool(inst and latest and installed_version != latest)
        rows.append(
            {
                "name": name,
                "latest_version": latest,
                "installed_version": installed_version or "—",
                "status": "outdated" if outdated else "",
                "description": _truncate(item.get("description") or ""),
            }
        )

    if not rows:
        if fmt == "json":
            print(json.dumps({"results": []}, indent=2))
        else:
            console.print("[dim]No skills available for your organization.[/dim]")
        return

    envelope = {
        "results": rows,
        "total": len(rows),
        "usage": data.get("usage"),
        "_breadcrumbs": data.get("_breadcrumbs", []),
    }
    output(envelope, fmt, columns=COLUMNS, title="Skills")


@app.command("download")
def download_cmd(
    name: str = typer.Argument(..., help="Skill name"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing directory that isn't tl-managed"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Download a skill and install it into every AI-agent skill directory on this machine.

    Installs into Claude Code's standalone skills directory, OpenCode's
    skills directory, and the directory shared by Gemini and Codex — the
    same targets `tl setup` uses for the bundled skill set. A destination
    that already exists and isn't tracked by a previous `tl skill download`
    is refused unless --force is passed; a destination tl previously
    installed is always replaced with the new version.

    Examples:
        tl skill download my-skill
        tl skill download my-skill --force
    """
    fmt = detect_format(json_output, False, False, toon_output)
    try:
        result = _download_and_install(name, force=force)
    except InvalidSkillNameError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except ApiError as e:
        handle_api_error(e)
        return
    except PathSafetyError as e:
        console.print(f"[red]Error:[/red] server response contains an unsafe path: {e}")
        raise typer.Exit(1)

    if fmt == "json":
        print(json.dumps(result, indent=2))
    else:
        for t in result["targets"]:
            if t["installed"]:
                console.print(f"  [green]✓[/green] {t['action']}: {t['path']}")
            else:
                console.print(f"  [red]✗[/red] {t['action']}: {t['path']} — {t['reason']}")
        console.print()

    if result["installed_count"] == 0:
        console.print(f"[red]{name} was not installed to any location.[/red]")
        raise typer.Exit(1)

    if fmt != "json":
        console.print(f"installed {name} v{result['version']} to {result['installed_count']} location(s)")


@app.command("update")
def update_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Refresh every downloaded skill to its latest available version.

    Skills no longer available to your organization are reported, not
    deleted — remove them explicitly with `tl skill remove <name>`.

    Examples:
        tl skill update
    """
    fmt = detect_format(json_output, False, False, toon_output)
    registry = read_registry()
    installed = registry.get("skills", {})
    if not installed:
        if fmt == "json":
            print(json.dumps({"updated": [], "gone": [], "unchanged": [], "failed": []}, indent=2))
        else:
            console.print("[dim]No downloaded skills to update.[/dim]")
        return

    client = get_client()
    try:
        names = ",".join(sorted(installed.keys()))
        data = client.get("/skills/versions/", params={"names": names})
    except ApiError as e:
        handle_api_error(e)
        return
    finally:
        client.close()

    latest_versions = data.get("results", {})
    updated: list[str] = []
    gone: list[str] = []
    unchanged: list[str] = []
    failed: list[dict] = []

    for name in sorted(installed.keys()):
        latest = latest_versions.get(name)
        current = installed[name].get("version")
        if not latest:
            gone.append(name)
            continue
        if latest == current:
            unchanged.append(name)
            continue
        try:
            _download_and_install(name, force=False)
            updated.append(name)
        except (ApiError, PathSafetyError, InvalidSkillNameError) as e:
            failed.append({"name": name, "error": str(e)})

    if fmt == "json":
        print(json.dumps({"updated": updated, "gone": gone, "unchanged": unchanged, "failed": failed}, indent=2))
        return

    if updated:
        console.print(f"[green]Updated:[/green] {', '.join(updated)}")
    if gone:
        console.print(f"[yellow]No longer available to your organization:[/yellow] {', '.join(gone)}")
        console.print("  Run [bold]tl skill remove <name>[/bold] to clean these up.")
    if unchanged:
        console.print(f"[dim]Already up to date: {', '.join(unchanged)}[/dim]")
    if failed:
        console.print(f"[red]Failed:[/red] {', '.join(f['name'] for f in failed)}")
    if not (updated or gone or unchanged or failed):
        console.print("[dim]Nothing to update.[/dim]")


@app.command("remove")
def remove_cmd(
    name: str = typer.Argument(..., help="Skill name"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Remove a downloaded skill from every location tl installed it.

    Only deletes a directory if it still carries the `.tl-skill.json`
    marker for this skill — a directory that's been manually replaced is
    left untouched and reported as skipped.

    Examples:
        tl skill remove my-skill
    """
    fmt = detect_format(json_output, False, False, toon_output)
    registry = read_registry()
    installed = registry.get("skills", {})
    entry = installed.get(name)
    if entry is None:
        console.print(f"[yellow]{name} is not in the local skill registry.[/yellow]")
        raise typer.Exit(1)

    removed: list[str] = []
    skipped: list[str] = []
    for path_str in entry.get("paths", []):
        path = Path(path_str)
        if is_marked_for(path, name):
            shutil.rmtree(path)
            removed.append(path_str)
        else:
            skipped.append(path_str)

    del installed[name]
    write_registry(registry)

    if fmt == "json":
        print(json.dumps({"name": name, "removed": removed, "skipped": skipped}, indent=2))
        return

    for p in removed:
        console.print(f"  [green]✓[/green] removed: {p}")
    for p in skipped:
        console.print(f"  [yellow]![/yellow] skipped (not tl-managed anymore): {p}")
    console.print(f"{name} removed from registry ({len(removed)} location(s) deleted)")
