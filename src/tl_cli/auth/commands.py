"""Auth CLI commands: tl auth login/logout/status."""

import sys
import time

import typer
from tl_cli._typer_utils import AlphaSortedTyperGroup
from rich.console import Console
from rich.prompt import Prompt

from tl_cli.auth.login import login_browser, login_device_code, revoke_refresh_token
from tl_cli.auth.token_store import KIND_API_KEY, StoredTokens, clear_tokens, load_tokens, save_tokens
from tl_cli.config import get_config

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Authentication commands")
console = Console(stderr=True)


def _read_masked(prompt: str) -> str:
    """Read a line of input echoing `*` for each character.

    Falls back to plain `input()` when stdin is not a TTY (piped input,
    test harness). Uses stdlib `termios` on Unix and `msvcrt` on Windows
    so no extra dependency is needed.
    """
    if not sys.stdin.isatty():
        return input(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()

    buf: list[str] = []
    if sys.platform == 'win32':
        import msvcrt
        while True:
            ch = msvcrt.getwch()
            if ch in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                break
            if ch == '\x03':  # Ctrl-C
                raise KeyboardInterrupt
            if ch in ('\b', '\x7f'):
                if buf:
                    buf.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
                continue
            buf.append(ch)
            sys.stdout.write('*')
            sys.stdout.flush()
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in ('\r', '\n'):
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    break
                if ch == '\x03':
                    raise KeyboardInterrupt
                if ch in ('\b', '\x7f'):
                    if buf:
                        buf.pop()
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                    continue
                buf.append(ch)
                sys.stdout.write('*')
                sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return ''.join(buf)


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

    key = _read_masked("Paste your API key: ").strip()
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
    """Log out: revoke the refresh token at Auth0, then clear stored tokens."""
    tokens = load_tokens()
    # Revoke the long-lived credential server-side so a leaked/synced copy of
    # the local token store can't keep minting access tokens. Best-effort —
    # API-key auth has no refresh token, and an offline revoke must not block
    # clearing local credentials.
    if tokens and not tokens.is_api_key and tokens.refresh_token:
        if revoke_refresh_token(tokens.refresh_token):
            console.print("[dim]Refresh token revoked at Auth0.[/dim]")
        else:
            console.print(
                "[yellow]Could not reach Auth0 to revoke the refresh token; "
                "clearing local credentials anyway.[/yellow]"
            )
        # Revoking the refresh token doesn't end the browser SSO session that
        # the interactive login established. Point the user at Auth0's logout
        # URL so the next `tl auth login` doesn't silently SSO straight back in.
        logout_url = f"https://{get_config().auth0_domain}/logout"
        console.print(
            f"To end your Auth0 browser session, visit: [cyan]{logout_url}[/cyan]"
        )
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
