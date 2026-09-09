"""Auth CLI commands: tl auth login/logout/status."""

import sys
import time

import typer
from tl_cli._typer_utils import AlphaSortedTyperGroup
from rich.console import Console
from rich.prompt import Prompt

from tl_cli.auth.login import (
    login_browser,
    login_device_code,
    open_in_browser,
    revoke_refresh_token,
    web_logout_url,
)
from tl_cli.auth.token_store import KIND_API_KEY, StoredTokens, clear_tokens, load_tokens, save_tokens
from tl_cli.client.errors import ApiError
from tl_cli.client.http import get_client
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


LOGIN_METHODS = {"browser": "1", "device": "2", "api-key": "3"}


def _interactive() -> bool:
    """Is a person at a terminal — i.e. may we ask a question or open a browser
    window? Output goes to stderr, so that is the stream that matters; stdout
    may well be a file or a pipe in a perfectly interactive session."""
    return sys.stdin.isatty() and sys.stderr.isatty()


@app.command("login", help="Log in to ThoughtLeaders.")
def login_cmd(
    method: str | None = typer.Option(
        None,
        "--method",
        "-m",
        help="Skip the menu: browser (OAuth2 on this machine), device (code for another "
        "device), or api-key. Required when there is no terminal to answer the menu.",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Browser method only: print the login URL instead of opening a browser. "
        "Implied when there is no terminal, so a window never pops up at an agent.",
    ),
) -> None:
    """Log in to ThoughtLeaders.

    The default flow opens a browser on this machine for OAuth2 (Auth0). If
    you are already signed in to the web platform in that browser, it
    completes without a password; either way it leaves the browser signed in
    to the platform too, and the Chrome extension follows. A device-code flow
    is available for headless environments, and a pre-issued API key can be
    configured for CI/scripts.
    """
    if method is not None:
        if method not in LOGIN_METHODS:
            console.print(
                f"[red]Unknown --method {method!r}.[/red] "
                f"Choose one of: {', '.join(LOGIN_METHODS)}"
            )
            raise typer.Exit(1)
        choice = LOGIN_METHODS[method]
    elif not _interactive():
        console.print(
            "[red]No terminal to answer the login menu.[/red] "
            "Pass --method browser, --method device or --method api-key."
        )
        raise typer.Exit(2)
    else:
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
        login_browser(open_browser=not no_browser and _interactive())


def _login_api_key() -> None:
    """Store a user-supplied API key as the active credential.

    No browser, no finalize call — the server has already issued this key
    against an existing user/organization. The stored record is tagged
    `kind=api_key` so the HTTP client sends `X-TL-Auth: API-KEY` on every
    request. We immediately call /whoami to (a) verify the key is valid and
    (b) capture the owning user's email for `tl auth status` output.
    """
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
def logout_cmd(
    local: bool = typer.Option(
        False,
        "--local",
        help="Only clear this machine's credentials. By default logout also signs you "
        "out of the web platform and the Chrome extension.",
    ),
) -> None:
    """Log out everywhere: tell the platform this session has ended (which
    signs out the extension and any other CLI), revoke the refresh token at
    Auth0, clear stored tokens, then end the web platform session in the
    browser. Pass --local to leave the other surfaces signed in."""
    tokens = load_tokens()
    if not local and tokens and not tokens.is_api_key:
        _sign_out_everywhere()
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
    clear_tokens()
    console.print("[green]Logged out successfully.[/green]")

    if local:
        return
    # Revoking the refresh token doesn't end the browser session the login
    # established — on the web platform, at Auth0, or in the extension. The
    # platform's logout page ends all of those, but only when a real browser
    # visits it. Drive it when we have one; otherwise hand over the URL rather
    # than popping a window from an agent or a script.
    logout_url = web_logout_url(get_config())
    if _interactive() and open_in_browser(logout_url):
        console.print("[dim]Signing you out of the web platform and extension in your browser.[/dim]")
    else:
        console.print(
            f"To also sign out of the web platform and extension, visit: [cyan]{logout_url}[/cyan]"
        )


def _sign_out_everywhere() -> None:
    """Best-effort: ask the platform to end this session everywhere. The
    platform then refuses every token this sign-in produced — the extension's
    and other CLIs' included — while this command goes on to clear its own.
    Nothing here may stop the local logout, so failures only get a note."""
    client = get_client()
    try:
        client.post("/auth/sign-out", json_body={})
        console.print("[dim]Signed out everywhere.[/dim]")
    except (ApiError, SystemExit):
        console.print("[yellow]Could not reach the platform to sign out everywhere; other surfaces stay signed in until they next check.[/yellow]")
    finally:
        client.close()


@app.command("status")
def status_cmd(
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Print nothing; exit 0 if logged in, 2 otherwise."
    ),
) -> None:
    """Show current authentication status: exit 0 when the next command will
    authenticate, 2 when it will not."""
    if get_config().api_key:
        # TL_API_KEY wins over anything stored (see the HTTP client), so this
        # machine is authenticated whatever the keychain holds.
        if not quiet:
            console.print("[green]Authenticated[/green] via API key from TL_API_KEY.")
        return

    tokens = load_tokens()
    if not tokens:
        if not quiet:
            console.print("[yellow]Not logged in.[/yellow] Run: tl auth login")
        raise SystemExit(2)

    # An expired access token with a refresh token is still a working session:
    # the next command refreshes it on its own.
    if tokens.is_expired and not tokens.refresh_token:
        if not quiet:
            console.print(f"[yellow]Token expired.[/yellow] Logged in as: {tokens.email or 'unknown'}")
            console.print("Run: tl auth login")
        raise SystemExit(2)

    if quiet:
        return
    if tokens.is_api_key:
        console.print("[green]Authenticated[/green] via API key.")
    else:
        console.print(f"[green]Authenticated[/green] as: {tokens.email or 'unknown'}")
