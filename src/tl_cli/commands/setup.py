"""tl setup — Install Claude Code plugin and other integrations."""

import shutil
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Set up integrations (Claude Code plugin)")
console = Console()

CLAUDE_PLUGINS_DIR = Path.home() / ".claude" / "plugins" / "tl-cli"
PLUGIN_COMPONENTS = [".claude-plugin", "commands", "skills", "agents", "hooks"]


def _find_plugin_root() -> Path | None:
    """Locate the plugin assets directory.

    Tries two locations:
    1. _plugin/ inside the installed package (pip/pipx installs via hatch force-include)
    2. Repo root relative to this file (editable installs)
    """
    # 1. Bundled inside the package (pip/pipx wheel install)
    bundled = Path(__file__).resolve().parent.parent / "_plugin"
    if (bundled / ".claude-plugin" / "plugin.json").is_file():
        return bundled

    # 2. Repo root (editable install: src/tl_cli/commands/setup.py → 4 levels up)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    if (repo_root / ".claude-plugin" / "plugin.json").is_file():
        return repo_root

    return None


def check_plugin_version() -> str | None:
    """Check if installed plugin version matches CLI version.

    Returns a warning message if mismatched or not installed, None if OK.
    """
    from tl_cli import __version__
    version_file = CLAUDE_PLUGINS_DIR / ".version"
    if not version_file.exists():
        if CLAUDE_PLUGINS_DIR.exists():
            return f"Claude Code plugin is installed but has no version stamp. Run 'tl setup claude' to update."
        return None  # Plugin not installed at all — not a mismatch, just not set up
    installed = version_file.read_text().strip()
    if installed != __version__:
        return f"Claude Code plugin is outdated (v{installed} vs CLI v{__version__}). Run 'tl setup claude' to update."
    return None


@app.command("claude")
def setup_claude() -> None:
    """Install the TL CLI plugin for Claude Code.

    Copies the plugin manifest, skill file, agent, hooks, and slash commands
    into ~/.claude/plugins/tl-cli/ so Claude Code can discover them.

    Examples:
        tl setup claude
    """
    plugin_root = _find_plugin_root()
    if plugin_root is None:
        console.print("[red]Plugin files not found.[/red]")
        console.print("This usually means the CLI was installed without plugin assets.")
        console.print("Try reinstalling: pipx install tl-cli")
        raise SystemExit(1)

    CLAUDE_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    for component in PLUGIN_COMPONENTS:
        src = plugin_root / component
        dst = CLAUDE_PLUGINS_DIR / component
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    # Write version stamp so we can detect stale plugins
    from tl_cli import __version__
    (CLAUDE_PLUGINS_DIR / ".version").write_text(__version__)

    console.print("[green]Claude Code plugin installed![/green]")
    console.print(f"  Source: {plugin_root}")
    console.print(f"  Installed to: {CLAUDE_PLUGINS_DIR}")
    console.print()
    console.print("Restart Claude Code to activate. Then try:")
    console.print("  [cyan]/tl sold sponsorships for Nike in Q1[/cyan]")
