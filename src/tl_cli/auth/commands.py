"""Auth CLI commands: tl auth login/logout/status."""

import time

import typer
from rich.console import Console
from rich.prompt import Prompt

from tl_cli.auth.finalize import finalize_signup
from tl_cli.auth.login import login_browser, login_device_code
from tl_cli.auth.token_store import KIND_API_KEY, StoredTokens, clear_tokens, load_tokens, save_tokens

app = typer.Typer(help="Authentication commands")
console = Console(stderr=True)


@app.command("login", help="Log in to ThoughtLeaders.")
def login_cmd() -> None:
    """Log in to ThoughtLeaders.

    The default flow opens a browser on this machine for OAuth2 (Auth0).
    A device-code flow is available for headless environments, and a
    pre-issued API key can be configured for CI/scripts.
    """
    console.print("[bold]How would you like to authenticate?[/bold]")
    console.print(
        "  [cyan]1[/cyan] — OAuth2 in a browser on this machine "
        "[dim](default — opens a URL in the local browser)[/dim]"
    )
    console.print("  [cyan]2[/cyan] — Device code (use a browser on another device)")
    console.print("  [cyan]3[/cyan] — API key (paste a pre-issued key; for CI / non-interactive use)")
    console.print()
    choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="1", console=console)

    if choice == "3":
        _login_api_key()
        return

    if choice == "2":
        login_device_code()
    else:
        login_browser()

    finalize_signup()


def _login_api_key() -> None:
    """Store a user-supplied API key as the active credential.

    No browser, no finalize call — the server has already issued this key
    against an existing user/organization. The stored record is tagged
    `kind=api_key` so the HTTP client sends `X-TL-Auth: API-KEY` on every
    request. We immediately call /whoami to (a) verify the key is valid and
    (b) capture the owning user's email for `tl auth status` output.
    """
    # Imported here to avoid pulling httpx/keyring into the module-level
    # import graph when callers just want `tl auth logout` / `status`.
    from tl_cli.client.errors import ApiError
    from tl_cli.client.http import get_client

    key = Prompt.ask("Paste your API key", console=console, password=True).strip()
    if not key:
        console.print("[red]No key provided.[/red]")
        raise typer.Exit(1)

    save_tokens(
        StoredTokens(
            access_token=key,
            refresh_token=None,
            expires_at=time.time() + 10 * 365 * 24 * 3600,
            email=None,
            kind=KIND_API_KEY,
        )
    )

    client = get_client()
    try:
        data = client.get("/whoami")
    except ApiError as e:
        clear_tokens()
        console.print(f"[red]API key rejected:[/red] {e.detail}")
        raise typer.Exit(1)
    finally:
        client.close()

    email = (data.get("user") or {}).get("email")
    if not email:
        clear_tokens()
        console.print(
            "[red]API key accepted but the server returned no email for the owning user.[/red] "
            "This usually means the user record is incomplete — contact support."
        )
        raise typer.Exit(1)

    save_tokens(
        StoredTokens(
            access_token=key,
            refresh_token=None,
            expires_at=time.time() + 10 * 365 * 24 * 3600,
            email=email,
            kind=KIND_API_KEY,
        )
    )
    console.print(f"[green]API key stored.[/green] Authenticated as: {email}")


@app.command("logout")
def logout_cmd() -> None:
    """Clear stored authentication tokens."""
    clear_tokens()
    console.print("[green]Logged out successfully.[/green]")


@app.command("status")
def status_cmd() -> None:
    """Show current authentication status."""
    tokens = load_tokens()
    if not tokens:
        console.print("[yellow]Not logged in.[/yellow] Run: tl auth login")
        raise SystemExit(2)

    if tokens.is_expired:
        console.print(f"[yellow]Token expired.[/yellow] Logged in as: {tokens.email or 'unknown'}")
        console.print("Run: tl auth login")
        raise SystemExit(2)

    if tokens.is_api_key:
        console.print("[green]Authenticated[/green] via API key.")
    else:
        console.print(f"[green]Authenticated[/green] as: {tokens.email or 'unknown'}")
