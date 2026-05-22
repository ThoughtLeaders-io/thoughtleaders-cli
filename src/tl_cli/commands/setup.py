"""tl setup — Install Claude Code plugin and other integrations.

Agents-style installs (Gemini / Codex): both CLIs read skills from
`~/.agents/skills/`, so they share a single install target. Any `tl
setup …` command that installs skill files also mirrors them there
whenever either `gemini` or `codex` is on PATH. Behaviour follows the
OpenCode pattern (full per-skill tree copy, .tl-version stamp).
"""

import json
import shutil
import subprocess
from pathlib import Path

import typer
from pytoon import encode as toon_encode
from rich.console import Console

from tl_cli import __version__

app = typer.Typer(help="Set up integrations (Claude Code, OpenCode, Gemini, Codex)")
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
    """Find the claude binary on PATH."""
    return shutil.which("claude")


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


def _print_manual_instructions() -> None:
    """Print manual install instructions when claude binary is not found."""
    console.print()
    console.print("[yellow]Claude Code binary not found on PATH.[/yellow]")
    console.print()
    console.print("Install Claude Code first, then run these commands inside Claude Code:")
    console.print()
    console.print(f"  [cyan]/plugin marketplace add {MARKETPLACE_SOURCE}[/cyan]")
    console.print(f"  [cyan]/plugin install {PLUGIN_KEY}[/cyan]")
    console.print()
    console.print("Or start Claude Code with the plugin loaded directly:")
    console.print()
    console.print(f"  [cyan]claude --plugin-dir /path/to/tl-cli[/cyan]")


@app.command("claude")
def setup_claude(
    json_output: bool = typer.Option(False, "--json", help="JSON output (non-interactive)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs, non-interactive)"),
) -> None:
    """Install the TL CLI plugin for Claude Code.

    Registers the ThoughtLeaders marketplace, installs the tl-cli plugin,
    and copies skills/commands to ~/.claude/ for short /tl invocation.
    If the claude binary is not on PATH, prints manual instructions.

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
        # Still install standalone skills even without claude binary
        console.print("  [yellow]![/yellow] claude binary not found on PATH")
        _install_standalone_skills_step(plugin_root)
        console.print()
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
            console.print("    Try running inside Claude Code:")
            console.print(f"    [cyan]/plugin install {PLUGIN_KEY}[/cyan]")
            raise SystemExit(1)

    # Step 3: Install standalone skills for short /tl invocation
    _install_standalone_skills_step(plugin_root)

    # Write version stamp
    version_dir = CLAUDE_PLUGINS_DIR / "tl-cli"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / ".version").write_text(__version__)

    console.print()
    console.print("[green]Setup complete![/green]")
    console.print()
    console.print("Available skills in Claude Code:")
    console.print("  [cyan]/tl[/cyan]                  — data analyst (smart query router)")
    console.print("  [cyan]/tl-sponsorships[/cyan]     — sponsorship lookup")
    console.print("  [cyan]/tl-reports[/cyan]          — saved reports")
    console.print("  [cyan]/tl-balance[/cyan]          — credit balance")
    console.print()
    console.print("Try it:")
    console.print("  [cyan]/tl Which channels did we sponsor in Q1?[/cyan]")
    console.print()
    console.print("[dim]To update, run: tl setup claude[/dim]")


def _install_standalone_skills_step(plugin_root: Path) -> None:
    """Install standalone skills and print status."""
    console.print("[bold]Installing skills for /tl shortcut...[/bold]")
    count = _install_standalone_skills(plugin_root)
    if count > 0:
        console.print(f"  [green]✓[/green] Installed {count} skills/commands to ~/.claude/")
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

    # Always install standalone skills
    count = _install_standalone_skills(plugin_root)
    result["standalone_skills_installed"] = count

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
