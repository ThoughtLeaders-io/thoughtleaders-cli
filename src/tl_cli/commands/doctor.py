"""tl doctor — Health check for auth, connectivity, and version."""

import platform
import shutil

import typer
from rich.console import Console

from tl_cli import __version__
from tl_cli.auth.token_store import load_tokens
from tl_cli.client.errors import ApiError
from tl_cli.client.http import get_client
from tl_cli.config import get_config

# Helper tools that AI agents using `tl --json` output frequently reach for.
# Not required, but life is much better with them.
_RECOMMENDED_TOOLS: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        "jq",
        "JSON processor — pipe `tl … --json` into `jq` for filtering/projection.",
        {
            "Linux": "apt install jq  /  dnf install jq  /  pacman -S jq",
            "Darwin": "brew install jq",
            "Windows": "winget install jqlang.jq",
        },
    ),
    (
        "rg",
        "ripgrep — fast text search across CLI output, transcripts, and the codebase.",
        {
            "Linux": "apt install ripgrep  /  dnf install ripgrep  /  pacman -S ripgrep",
            "Darwin": "brew install ripgrep",
            "Windows": "winget install BurntSushi.ripgrep.MSVC",
        },
    ),
)

app = typer.Typer(help="Health check (auth, connectivity, version)")
console = Console()


@app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context) -> None:
    """Check CLI health: version, auth status, API connectivity, credits."""
    console.print(f"\n[bold]tl-cli[/bold] v{__version__}\n")
    config = get_config()
    all_ok = True

    # API URL
    console.print(f"  API:    {config.cli_api_base}")

    # Auth
    tokens = load_tokens()
    if not tokens:
        console.print("  Auth:   [red]not logged in[/red]")
        all_ok = False
    elif tokens.is_expired:
        console.print(f"  Auth:   [yellow]token expired[/yellow] ({tokens.email})")
        all_ok = False
    else:
        console.print(f"  Auth:   [green]ok[/green] ({tokens.email})")

    # Connectivity + balance
    if tokens and not tokens.is_expired:
        client = get_client()
        try:
            data = client.get("/balance")
            balance_val = data.get("balance", "?")
            console.print(f"  API:    [green]connected[/green]")
            console.print(f"  Credits: {balance_val}")
        except ApiError as e:
            console.print(f"  API:    [red]error ({e.status_code})[/red]")
            all_ok = False
        except Exception as e:
            console.print(f"  API:    [red]unreachable[/red]")
            all_ok = False
        finally:
            client.close()
    else:
        console.print("  API:    [dim]skipped (not authenticated)[/dim]")

    # Plugin/skill versions
    from tl_cli.commands.setup import check_plugin_version
    warnings = check_plugin_version()
    if warnings:
        for warn in warnings:
            console.print(f"  Plugin: [yellow]{warn}[/yellow]")
        all_ok = False
    else:
        console.print("  Plugin: [green]ok[/green]")

    # Recommended companion tools (jq, rg). Missing tools are advisory — they
    # don't flip all_ok to false.
    system = platform.system()
    missing: list[tuple[str, str, str | None]] = []
    for name, purpose, install_hints in _RECOMMENDED_TOOLS:
        if shutil.which(name):
            console.print(f"  {name}:     [green]found[/green]")
        else:
            hint = install_hints.get(system)
            console.print(f"  {name}:     [yellow]not found[/yellow]")
            missing.append((name, purpose, hint))

    if missing:
        console.print()
        console.print("[bold]Recommended tools to install:[/bold]")
        for name, purpose, hint in missing:
            console.print(f"  [cyan]{name}[/cyan] — {purpose}")
            if hint:
                console.print(f"    Install: {hint}")

    console.print()
    if all_ok:
        console.print("[green]Everything looks good.[/green]")
    else:
        console.print("[yellow]Issues found.[/yellow]")
