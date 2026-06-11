"""tl setup — Install Claude Code plugin and other integrations.

Agents-style installs (Gemini / Codex): both CLIs read skills from
`~/.agents/skills/`, so they share a single install target. Any `tl
setup …` command that installs skill files also mirrors them there
whenever either `gemini` or `codex` is on PATH. Behaviour follows the
OpenCode pattern (full per-skill tree copy, .tl-version stamp).
"""

import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from tl_cli._typer_utils import AlphaSortedTyperGroup
from pytoon import encode as toon_encode
from rich.console import Console

from tl_cli import __version__

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Set up integrations (Claude Code, OpenCode, Gemini, Codex)")
console = Console(stderr=True)

MARKETPLACE_SOURCE = "ThoughtLeaders-io/thoughtleaders-cli"
MARKETPLACE_NAME = "thoughtleaders-plugins"
PLUGIN_NAME = "tl-cli"
PLUGIN_KEY = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"

CLAUDE_HOME = Path.home() / ".claude"
CLAUDE_PLUGINS_DIR = CLAUDE_HOME / "plugins"
CLAUDE_SKILLS_DIR = CLAUDE_HOME / "skills"
CLAUDE_COMMANDS_DIR = CLAUDE_HOME / "commands"

OPENCODE_SKILLS_DIR = Path.home() / ".config" / "opencode" / "skills"

# Shared install target for the "agents-style" CLIs that read skills from
# `~/.agents/skills/`. Whenever any of these binaries is on PATH we mirror
# the skill tree there once — the directory is the same regardless of
# which CLI triggered the install.
AGENTS_SKILLS_DIR = Path.home() / ".agents" / "skills"
AGENTS_SKILLS_BINARIES = ("gemini", "codex")

# Personal-command shim that keeps the short `/tl` invocation working when the
# skills are provided (namespaced) by the installed plugin. Plugin skills and
# commands are always invoked as `/tl-cli:<name>`; this one-file pointer in
# ~/.claude/commands/ restores plain `/tl` without duplicating any skill
# content, so plugin updates flow through automatically.
TL_COMMAND_SHIM = """\
---
description: ThoughtLeaders data analyst — shortcut for the tl-cli plugin's tl skill
---

Invoke the `tl-cli:tl` skill with this request: $ARGUMENTS
"""


def _find_plugin_root() -> Path | None:
    """Locate the plugin assets directory.

    Tries two locations:
    1. _plugin/ inside the installed package (pip/pipx installs via hatch force-include)
    2. Repo root relative to this file (editable installs)
    """
    bundled = Path(__file__).resolve().parent.parent / "_plugin"
    if (bundled / ".claude-plugin" / "plugin.json").is_file():
        return bundled

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    if (repo_root / ".claude-plugin" / "plugin.json").is_file():
        return repo_root

    return None


def _find_claude_binary() -> str | None:
    """Find the claude binary on PATH, falling back to known install locations.

    On Windows the Claude Code installers often don't end up on the PATH of
    the shell running `tl` (stale PATH, PowerShell-only profile changes), so
    after `shutil.which` we probe the documented install targets directly:
    the native installer (`~/.local/bin`) and the npm global prefix.
    """
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    if sys.platform == "win32":
        candidates = [
            home / ".local" / "bin" / "claude.exe",
            Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "npm" / "claude.cmd",
        ]
    else:
        candidates = [
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _run_claude(args: list[str], claude_bin: str) -> tuple[bool, str]:
    """Run a claude CLI command and return (success, output)."""
    try:
        result = subprocess.run(
            [claude_bin] + args,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            output = result.stderr.strip() or output
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def _get_installed_plugin_version() -> str | None:
    """Try to read the installed plugin version from the cache."""
    version_file = CLAUDE_PLUGINS_DIR / "tl-cli" / ".version"
    if version_file.exists():
        return version_file.read_text().strip()
    return None


def check_plugin_version() -> list[str]:
    """Check if installed plugin versions match CLI version.

    Returns a list of warning messages for outdated installs. Empty if all OK.
    """
    warnings = []

    # Claude Code
    claude_version_file = CLAUDE_PLUGINS_DIR / "tl-cli" / ".version"
    if claude_version_file.exists():
        installed = claude_version_file.read_text().strip()
        if installed != __version__:
            warnings.append(f"Claude Code plugin is outdated (v{installed} vs CLI v{__version__}). Run 'tl setup claude' to update.")

    # OpenCode
    opencode_version_file = OPENCODE_SKILLS_DIR / ".tl-version"
    if opencode_version_file.exists():
        installed = opencode_version_file.read_text().strip()
        if installed != __version__:
            warnings.append(f"OpenCode skill is outdated (v{installed} vs CLI v{__version__}). Run 'tl setup opencode' to update.")

    # Gemini / Codex (shared ~/.agents/skills/ target)
    agents_version_file = AGENTS_SKILLS_DIR / ".tl-version"
    if agents_version_file.exists():
        installed = agents_version_file.read_text().strip()
        if installed != __version__:
            warnings.append(
                f"Gemini/Codex skills are outdated (v{installed} vs CLI v{__version__}). "
                f"Run 'tl setup gemini' or 'tl setup codex' to update."
            )

    return warnings


def _install_standalone_skills(plugin_root: Path) -> int:
    """Copy skills and commands to ~/.claude/ for non-namespaced invocation.

    Returns the number of items installed.
    """
    count = 0

    # Skills: skills/<name>/SKILL.md → ~/.claude/skills/<name>/SKILL.md
    skills_src = plugin_root / "skills"
    if skills_src.is_dir():
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                dst = CLAUDE_SKILLS_DIR / skill_dir.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(skill_dir, dst)
                count += 1

    # Commands: commands/<name>.md → ~/.claude/commands/<name>.md
    commands_src = plugin_root / "commands"
    if commands_src.is_dir():
        CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
        for cmd_file in commands_src.glob("*.md"):
            dst = CLAUDE_COMMANDS_DIR / cmd_file.name
            shutil.copy2(cmd_file, dst)
            count += 1

    return count


def _install_command_shim() -> Path:
    """Write the `/tl` shim command to ~/.claude/commands/tl.md."""
    CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    dst = CLAUDE_COMMANDS_DIR / "tl.md"
    dst.write_text(TL_COMMAND_SHIM, encoding="utf-8")
    return dst


def _trees_identical(a: Path, b: Path) -> bool:
    """True if two directory trees contain the same files with the same contents."""
    a_files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    b_files = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    if a_files != b_files:
        return False
    return all(filecmp.cmp(a / rel, b / rel, shallow=False) for rel in a_files)


def _remove_matching_standalone_skills(plugin_root: Path) -> tuple[int, int]:
    """Remove standalone copies in ~/.claude/skills/ that match the plugin's skills.

    Earlier versions of `tl setup claude` copied every bundled skill into
    ~/.claude/skills/. Now that the plugin provides them, those copies are
    redundant — but a copy is only deleted when its tree is byte-identical
    to the bundled skill, so user-modified copies are never touched.
    Returns (removed, kept_modified).
    """
    removed = kept = 0
    skills_src = plugin_root / "skills"
    if not skills_src.is_dir():
        return removed, kept
    for skill_dir in skills_src.iterdir():
        if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file()):
            continue
        standalone = CLAUDE_SKILLS_DIR / skill_dir.name
        if not standalone.is_dir():
            continue
        if _trees_identical(skill_dir, standalone):
            shutil.rmtree(standalone)
            removed += 1
        else:
            kept += 1
    return removed, kept


def _bundled_skill_blurbs(plugin_root: Path) -> list[tuple[str, str]]:
    """Read (name, tl-blurb) for each bundled skill, for the setup summary.

    Reads the `tl-blurb` frontmatter key from skills/<name>/SKILL.md so the
    summary stays in sync with the skills actually shipped — no hand-maintained
    list to drift. Skills without the key are skipped. Sorted by name.
    """
    skills_src = plugin_root / "skills"
    if not skills_src.is_dir():
        return []
    blurbs: list[tuple[str, str]] = []
    for skill_dir in skills_src.iterdir():
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        name = blurb = None
        in_frontmatter = False
        for line in skill_md.read_text(encoding="utf-8").splitlines():
            if line.strip() == "---":
                if in_frontmatter:
                    break
                in_frontmatter = True
                continue
            if not in_frontmatter:
                continue
            if line.startswith("name:"):
                name = line[len("name:"):].strip()
            elif line.startswith("tl-blurb:"):
                blurb = line[len("tl-blurb:"):].strip()
        if name and blurb:
            blurbs.append((name, blurb))
    blurbs.sort(key=lambda nb: nb[0])
    return blurbs


def _print_manual_instructions() -> None:
    """Print manual install instructions when the plugin couldn't be installed."""
    console.print()
    console.print("[yellow]The Claude Code plugin could not be installed automatically.[/yellow]")
    console.print()
    console.print(f"The skills were installed to {CLAUDE_SKILLS_DIR} instead — restart")
    console.print("Claude Code and they will be available (e.g. [cyan]/tl[/cyan]).")
    console.print()
    console.print("To install the full plugin, run these commands inside Claude Code:")
    console.print()
    console.print(f"  [cyan]/plugin marketplace add {MARKETPLACE_SOURCE}[/cyan]")
    console.print(f"  [cyan]/plugin install {PLUGIN_KEY}[/cyan]")
    console.print()
    console.print("then re-run [cyan]tl setup claude[/cyan] to clean up the standalone copies.")


@app.command("claude")
def setup_claude(
    json_output: bool = typer.Option(False, "--json", help="JSON output (non-interactive)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs, non-interactive)"),
) -> None:
    """Install the TL CLI plugin for Claude Code.

    Registers the ThoughtLeaders marketplace, installs the tl-cli plugin,
    and adds a /tl shim command so the plugin's tl skill can be invoked
    without the plugin namespace. Standalone skill copies in ~/.claude/skills
    are only installed as a fallback when the plugin can't be installed;
    unmodified copies left by earlier versions are removed.

    Examples:
        tl setup claude
        tl setup claude --json
    """
    if json_output or toon_output:
        _setup_noninteractive(fmt="toon" if toon_output else "json")
        return

    console.print()
    console.print(f"[bold]tl-cli[/bold] v{__version__} — Claude Code Plugin Setup")
    console.print()

    # Check tl is on PATH
    tl_bin = shutil.which("tl")
    if tl_bin:
        console.print(f"  [green]✓[/green] tl CLI found: {tl_bin}")
    else:
        console.print("  [red]✗[/red] tl CLI not found on PATH")
        console.print("    Claude Code's Bash tool won't be able to run tl commands.")
        console.print("    Install with: [cyan]pipx install thoughtleaders-cli[/cyan]")

    # Find plugin assets
    plugin_root = _find_plugin_root()
    if plugin_root is None:
        console.print("  [red]✗[/red] Plugin assets not found")
        console.print("    Try reinstalling: [cyan]pipx install thoughtleaders-cli[/cyan]")
        raise SystemExit(1)
    console.print(f"  [green]✓[/green] Plugin assets found: {plugin_root}")

    # Check claude binary
    claude_bin = _find_claude_binary()
    if not claude_bin:
        # Fall back to standalone skill copies when the plugin can't be installed
        console.print("  [yellow]![/yellow] claude binary not found")
        _install_standalone_skills_step(plugin_root)
        _print_manual_instructions()
        raise SystemExit(1)

    console.print(f"  [green]✓[/green] claude binary found: {claude_bin}")
    console.print()

    # Step 1: Register marketplace
    console.print("[bold]Registering marketplace...[/bold]")
    ok, output = _run_claude(["plugin", "marketplace", "add", MARKETPLACE_SOURCE], claude_bin)
    if ok:
        console.print(f"  [green]✓[/green] Marketplace registered: {MARKETPLACE_NAME}")
    else:
        if "already" in output.lower() or "exists" in output.lower():
            console.print(f"  [green]✓[/green] Marketplace already registered: {MARKETPLACE_NAME}")
            console.print("  Updating marketplace...")
            _run_claude(["plugin", "marketplace", "update", MARKETPLACE_NAME], claude_bin)
        else:
            console.print(f"  [red]✗[/red] Marketplace registration failed: {output}")
            _install_standalone_skills_step(plugin_root)
            _print_manual_instructions()
            raise SystemExit(1)

    # Step 2: Install plugin
    console.print("[bold]Installing plugin...[/bold]")
    ok, output = _run_claude(["plugin", "install", PLUGIN_KEY], claude_bin)
    if ok:
        console.print(f"  [green]✓[/green] Plugin installed: {PLUGIN_KEY}")
    else:
        if "already" in output.lower():
            console.print(f"  [green]✓[/green] Plugin already installed: {PLUGIN_KEY}")
        else:
            console.print(f"  [red]✗[/red] Plugin installation failed: {output}")
            _install_standalone_skills_step(plugin_root)
            _print_manual_instructions()
            raise SystemExit(1)

    # Step 3: /tl shim command + cleanup of standalone copies from older versions
    console.print("[bold]Installing /tl shortcut...[/bold]")
    shim = _install_command_shim()
    console.print(f"  [green]✓[/green] /tl command installed: {shim}")
    removed, kept = _remove_matching_standalone_skills(plugin_root)
    if removed:
        console.print(f"  [green]✓[/green] Removed {removed} standalone skill(s) now provided by the plugin")
    if kept:
        console.print(f"  [yellow]![/yellow] Kept {kept} modified standalone skill(s) in {CLAUDE_SKILLS_DIR}")
        console.print("    These differ from the plugin's versions and shadow nothing — remove manually if unwanted.")

    # Write version stamp
    version_dir = CLAUDE_PLUGINS_DIR / "tl-cli"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / ".version").write_text(__version__)

    console.print()
    console.print("[green]Setup complete![/green]")
    console.print()
    console.print("Available skills in Claude Code:")
    blurbs = _bundled_skill_blurbs(plugin_root)
    width = max((len(name) for name, _ in blurbs), default=0)
    for name, blurb in blurbs:
        console.print(f"  [cyan]/{PLUGIN_NAME}:{name}[/cyan]{' ' * (width - len(name))}  — {blurb}")
    console.print()
    console.print("Try it (restart Claude Code first):")
    console.print("  [cyan]/tl Which channels did we sponsor in Q1?[/cyan]")
    console.print()
    console.print("[dim]To update, run: tl setup claude[/dim]")


def _install_standalone_skills_step(plugin_root: Path) -> None:
    """Install standalone skills (plugin-less fallback) and print status."""
    console.print("[bold]Installing standalone skills (plugin fallback)...[/bold]")
    count = _install_standalone_skills(plugin_root)
    if count > 0:
        console.print(f"  [green]✓[/green] Installed {count} skills/commands to {CLAUDE_HOME}")
    else:
        console.print("  [yellow]![/yellow] No skills found to install")


def _emit_setup_result(result: dict, fmt: str) -> None:
    """Emit a setup-status dict in JSON (default) or TOON."""
    if fmt == "toon":
        print(toon_encode(result))
    else:
        print(json.dumps(result, indent=2))


def _setup_noninteractive(fmt: str = "json") -> None:
    """Non-interactive setup for --json / --toon / agent usage."""
    result = {
        "cli_version": __version__,
        "marketplace_source": MARKETPLACE_SOURCE,
        "marketplace_name": MARKETPLACE_NAME,
        "plugin_key": PLUGIN_KEY,
    }

    plugin_root = _find_plugin_root()
    if plugin_root is None:
        result["status"] = "error"
        result["error"] = "Plugin assets not found"
        _emit_setup_result(result, fmt)
        raise SystemExit(1)

    claude_bin = _find_claude_binary()

    # Register marketplace + install plugin (if claude binary available)
    if claude_bin:
        ok, output = _run_claude(["plugin", "marketplace", "add", MARKETPLACE_SOURCE], claude_bin)
        if not ok and "already" not in output.lower() and "exists" not in output.lower():
            result["marketplace_registered"] = False
        else:
            result["marketplace_registered"] = True
            _run_claude(["plugin", "marketplace", "update", MARKETPLACE_NAME], claude_bin)

        ok, output = _run_claude(["plugin", "install", PLUGIN_KEY], claude_bin)
        result["plugin_installed"] = ok or "already" in output.lower()
    else:
        result["marketplace_registered"] = False
        result["plugin_installed"] = False

    if result["plugin_installed"]:
        # Plugin provides the skills; install the /tl shim and clean up
        # unmodified standalone copies left by earlier versions.
        _install_command_shim()
        removed, kept = _remove_matching_standalone_skills(plugin_root)
        result["command_shim_installed"] = True
        result["standalone_skills_installed"] = 0
        result["standalone_skills_removed"] = removed
        result["standalone_skills_kept_modified"] = kept
    else:
        # Fallback: standalone skill copies so Claude Code still gets /tl
        result["command_shim_installed"] = False
        result["standalone_skills_installed"] = _install_standalone_skills(plugin_root)

    # Write version stamp
    version_dir = CLAUDE_PLUGINS_DIR / "tl-cli"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / ".version").write_text(__version__)

    result["status"] = "ok"
    _emit_setup_result(result, fmt)


# --- OpenCode setup ---


def _install_skill_trees(plugin_root: Path, target_dir: Path) -> int:
    """Copy every `skills/<name>/` tree under `plugin_root` into `target_dir`.

    Shared primitive used by every "external agent" install path
    (OpenCode, Gemini, Codex) — each agent reads skills from a different
    base directory, so we just parameterise on that. A `.tl-version`
    stamp is written into the target so `check_plugin_version()` can
    detect drift later. Returns the number of skills installed.
    """
    count = 0
    skills_src = plugin_root / "skills"
    if skills_src.is_dir():
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                dst = target_dir / skill_dir.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(skill_dir, dst)
                count += 1
    if count > 0 or target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / ".tl-version").write_text(__version__)
    return count


# Back-compat names — both delegate to the shared primitive. Kept so other
# modules that import them continue to work without changes.
def _install_opencode_skills(plugin_root: Path) -> int:
    return _install_skill_trees(plugin_root, OPENCODE_SKILLS_DIR)


def _install_agents_skills(plugin_root: Path) -> int:
    return _install_skill_trees(plugin_root, AGENTS_SKILLS_DIR)


def _setup_external_agent(
    *,
    agent_label: str,
    agent_binary: str,
    command_name: str,
    target_dir: Path,
    post_install_lines: list[str] | None,
    json_output: bool,
    toon_output: bool = False,
) -> None:
    """Shared body for the OpenCode / Gemini / Codex setup commands.

    All three follow the same shape: copy skill trees into a target
    directory, stamp a `.tl-version` file, print a status report.
    Arguments customise the diagnostic text and the install target.
    Auto-discovery between agents has been intentionally removed —
    `tl update` is responsible for re-syncing every detected agent
    after a self-upgrade; the per-agent setup commands stay scoped to
    their one agent.
    """
    plugin_root = _find_plugin_root()

    if json_output or toon_output:
        fmt = "toon" if toon_output else "json"
        result: dict = {"cli_version": __version__}
        if plugin_root is None:
            result["status"] = "error"
            result["error"] = "Plugin assets not found"
            _emit_setup_result(result, fmt)
            raise SystemExit(1)
        result[f"{agent_binary}_detected"] = shutil.which(agent_binary) is not None
        count = _install_skill_trees(plugin_root, target_dir)
        result["skills_installed"] = count
        result["install_dir"] = str(target_dir)
        result["status"] = "ok"
        _emit_setup_result(result, fmt)
        return

    console.print()
    console.print(f"[bold]tl-cli[/bold] v{__version__} — {agent_label} Setup")
    console.print()

    tl_bin = shutil.which("tl")
    if tl_bin:
        console.print(f"  [green]✓[/green] tl CLI found: {tl_bin}")
    else:
        console.print("  [red]✗[/red] tl CLI not found on PATH")
        console.print(f"    {agent_label}'s shell tool won't be able to run tl commands.")
        console.print("    Install with: [cyan]pipx install git+https://github.com/ThoughtLeaders-io/thoughtleaders-cli.git[/cyan]")

    agent_bin = shutil.which(agent_binary)
    if agent_bin:
        console.print(f"  [green]✓[/green] {agent_binary} binary found: {agent_bin}")
    else:
        console.print(f"  [yellow]![/yellow] {agent_binary} binary not found on PATH (installing skills anyway)")

    if plugin_root is None:
        console.print("  [red]✗[/red] Plugin assets not found")
        console.print("    Try reinstalling: [cyan]pipx install --force git+https://github.com/ThoughtLeaders-io/thoughtleaders-cli.git[/cyan]")
        raise SystemExit(1)
    console.print(f"  [green]✓[/green] Plugin assets found: {plugin_root}")
    console.print()

    console.print("[bold]Installing skills...[/bold]")
    count = _install_skill_trees(plugin_root, target_dir)
    if count > 0:
        console.print(f"  [green]✓[/green] Installed {count} skill(s) to {target_dir}/")
    else:
        console.print("  [yellow]![/yellow] No skills found to install")
        raise SystemExit(1)

    console.print()
    console.print("[green]Setup complete![/green]")
    console.print()
    for line in post_install_lines or []:
        console.print(line)
    if post_install_lines:
        console.print()
    console.print(f"[dim]To update, run: tl setup {command_name}[/dim]")


@app.command("opencode")
def setup_opencode(
    json_output: bool = typer.Option(False, "--json", help="JSON output (non-interactive)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs, non-interactive)"),
) -> None:
    """Install the TL CLI skills for OpenCode.

    Copies skill files to ~/.config/opencode/skills/ so OpenCode's
    agent can discover and use them automatically.

    Examples:
        tl setup opencode
        tl setup opencode --json
    """
    _setup_external_agent(
        agent_label="OpenCode",
        agent_binary="opencode",
        command_name="opencode",
        target_dir=OPENCODE_SKILLS_DIR,
        post_install_lines=[
            "OpenCode will automatically discover the tl skill.",
            "The agent can use it when you ask about sponsorships, deals, channels, or brands.",
        ],
        json_output=json_output,
        toon_output=toon_output,
    )


# --- Gemini / Codex setup (shared ~/.agents/skills/ target) ---


@app.command("gemini")
def setup_gemini(
    json_output: bool = typer.Option(False, "--json", help="JSON output (non-interactive)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs, non-interactive)"),
) -> None:
    """Install the TL CLI skills for the Gemini CLI.

    Copies skill files to ~/.agents/skills/ so the Gemini CLI can
    discover and use them automatically. Shares its install target with
    `tl setup codex` — running either installs the same files.

    Examples:
        tl setup gemini
        tl setup gemini --json
    """
    _setup_external_agent(
        agent_label="Gemini",
        agent_binary="gemini",
        command_name="gemini",
        target_dir=AGENTS_SKILLS_DIR,
        post_install_lines=None,
        json_output=json_output,
        toon_output=toon_output,
    )


@app.command("codex")
def setup_codex(
    json_output: bool = typer.Option(False, "--json", help="JSON output (non-interactive)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs, non-interactive)"),
) -> None:
    """Install the TL CLI skills for the Codex CLI.

    Copies skill files to ~/.agents/skills/ so the Codex CLI can
    discover and use them automatically. Shares its install target with
    `tl setup gemini` — running either installs the same files.

    Examples:
        tl setup codex
        tl setup codex --json
    """
    _setup_external_agent(
        agent_label="Codex",
        agent_binary="codex",
        command_name="codex",
        target_dir=AGENTS_SKILLS_DIR,
        post_install_lines=None,
        json_output=json_output,
        toon_output=toon_output,
    )
