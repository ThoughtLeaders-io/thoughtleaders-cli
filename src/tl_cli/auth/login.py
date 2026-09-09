"""Auth0 login flows: browser-based PKCE and headless device code."""

import base64
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass

import httpx
from rich.console import Console

from tl_cli.auth.pkce import generate_pkce_pair
from tl_cli.auth.token_store import StoredTokens, clear_tokens, load_tokens, save_tokens
from tl_cli.config import DEFAULT_AUTH0_CALLBACK_PORT, get_config

console = Console(stderr=True)


@dataclass
class _CallbackResult:
    """Captured from the OAuth callback."""

    code: str | None = None
    error: str | None = None
    state: str | None = None


def web_signin_url(config) -> str:
    """Where the browser goes once the CLI login has completed.

    The platform's `/signin?go=1` jumps straight to Auth0; with the SSO cookie
    the login just created, that round trip completes silently and leaves the
    browser signed in to the web platform too. The Chrome extension adopts the
    web session from that page load, so one login covers all three surfaces.
    `from=cli` lets the platform land on a page that says so.
    """
    return f"{config.api_url.rstrip('/')}/signin?go=1&from=cli"


def web_logout_url(config, web_only: bool = False) -> str:
    """The platform's logout page. It ends the web session and the Auth0 session
    on the shared domain, so the SSO cookie the CLI login created goes too, and
    unless `web_only` it records the sign-out for every other surface. The CLI
    asks for `web_only` once it has recorded the sign-out through the API
    itself: a second, later record could refuse a sign-in the user has meanwhile
    started. When that call did not get through, the page is the fallback.
    """
    base = f"{config.api_url.rstrip('/')}/logout"
    return f"{base}?web_only=1" if web_only else base


def login_browser(open_browser: bool = True) -> StoredTokens:
    """Run the Auth0 PKCE login flow with a local browser.

    1. Generate PKCE pair + state
    2. Start localhost callback server
    3. Open browser to Auth0 /authorize (or just print the URL)
    4. Wait for callback with authorization code; send the browser on to the
       platform's sign-in so the web session (and the extension) follow
    5. Exchange code for tokens
    6. Store tokens
    """
    config = get_config()
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    result = _CallbackResult()

    # Start callback server on the fixed port (must match Auth0 allowed callback URLs)
    try:
        server, port = _start_callback_server(
            result, state, DEFAULT_AUTH0_CALLBACK_PORT, success_redirect=web_signin_url(config)
        )
    except OSError as exc:
        console.print(
            f"[red]Could not listen on port {DEFAULT_AUTH0_CALLBACK_PORT} for the login callback "
            f"({exc.strerror or exc}).[/red] Close whatever is using it, or run: "
            "tl auth login --method device"
        )
        raise SystemExit(1) from exc

    redirect_uri = f"http://localhost:{port}/callback"

    # Build authorization URL
    params = {
        "response_type": "code",
        "client_id": config.auth0_client_id,
        "redirect_uri": redirect_uri,
        "audience": config.auth0_audience,
        "scope": "openid profile email offline_access",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    auth_url = f"https://{config.auth0_domain}/authorize?{urllib.parse.urlencode(params)}"

    if open_browser:
        console.print("[bold]Opening browser for login...[/bold]")
        console.print(f"[dim]If the browser doesn't open, visit:[/dim]\n{auth_url}\n")
        open_in_browser(auth_url)
    else:
        console.print(f"[bold]Open this URL in a browser on this machine:[/bold]\n{auth_url}\n")

    # Wait for callback (timeout after 120 seconds)
    deadline = time.time() + 120
    while result.code is None and result.error is None:
        if time.time() > deadline:
            server.shutdown()
            server.server_close()
            console.print("[red]Login timed out. Please try again.[/red]")
            raise SystemExit(1)
        time.sleep(0.1)

    server.shutdown()
    server.server_close()

    if result.error:
        console.print(f"[red]Login failed: {result.error}[/red]")
        raise SystemExit(1)

    # Exchange code for tokens
    console.print("[dim]Exchanging authorization code...[/dim]")
    tokens = _exchange_code(
        code=result.code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        config=config,
    )

    save_tokens(tokens)
    console.print(f"[green]Logged in as {tokens.email or 'unknown'}[/green]")
    return tokens


def login_device_code() -> StoredTokens:
    """Run the Auth0 Device Authorization Flow (RFC 8628).

    Works on headless machines — the user authenticates via any browser on any device.
    """
    config = get_config()

    # Request a device code
    response = httpx.post(
        f"https://{config.auth0_domain}/oauth/device/code",
        data={
            "client_id": config.auth0_client_id,
            "scope": "openid profile email offline_access",
            "audience": config.auth0_audience,
        },
    )

    if response.status_code != 200:
        console.print(f"[red]Failed to start device login: {response.text}[/red]")
        raise SystemExit(1)

    data = response.json()
    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    verification_uri_complete = data.get("verification_uri_complete", verification_uri)
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    console.print()
    console.print("[bold]To log in, open this URL on any device:[/bold]")
    console.print(f"  {verification_uri_complete}")
    console.print()
    console.print(f"[bold]And enter the code:[/bold]  [cyan bold]{user_code}[/cyan bold]")
    console.print()
    console.print(f"[dim]The code expires in {expires_in // 60} minutes. After you have logged in successfully, please wait until the system is notified.[/dim]")

    # Poll for token
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)

        token_response = httpx.post(
            f"https://{config.auth0_domain}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": config.auth0_client_id,
            },
        )

        token_data = token_response.json()

        if token_response.status_code == 200:
            # Extract email from ID token if present
            email = None
            id_token = token_data.get("id_token")
            if id_token:
                email = _extract_email_from_jwt(id_token)

            tokens = StoredTokens(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                expires_at=time.time() + token_data.get("expires_in", 3600),
                email=email,
                signed_in_at=signed_in_time(token_data["access_token"]),
            )
            save_tokens(tokens)
            console.print(f"\n[green]Logged in as {tokens.email or 'unknown'}[/green]")
            return tokens

        error = token_data.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            console.print("[red]Device code expired. Please try again.[/red]")
            raise SystemExit(1)
        elif error == "access_denied":
            console.print("[red]Login was denied.[/red]")
            raise SystemExit(1)
        else:
            console.print(f"[red]Login failed: {token_data.get('error_description', error)}[/red]")
            raise SystemExit(1)

    console.print("[red]Login timed out. Please try again.[/red]")
    raise SystemExit(1)


def open_in_browser(url: str) -> bool:
    """Open `url` in the user's browser. False when it could not be opened —
    a missing or misconfigured browser raises from `webbrowser` on some
    platforms, and the caller always has a URL to print instead."""
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001 — anything here just means "print the URL"
        return False


def forget_session(
    rejected_access_token: str | None = None, rejected_signed_in_at: float | None = None
) -> None:
    """Drop this machine's session after the server refused it as signed out.

    A 401 with `code: signed_out` means these credentials belong to a session
    the user has since ended — on the web, from the extension, or from another
    CLI. Refreshing would only mint another token for it, so the CLI revokes
    its refresh token (best-effort) and clears the store, as `tl auth logout
    --local` does. Two cases are left alone: an API key, which is not a session
    and cannot be re-obtained by `tl auth login`; and a store that now holds a
    different session — a new sign-in has replaced the one the verdict was
    about. A session is known by when it was signed in, which survives the
    token refreshes other `tl` processes may have done meanwhile; only a store
    from before that was recorded is compared by access token.
    """
    tokens = load_tokens()
    if tokens is None or tokens.is_api_key:
        return
    if tokens.signed_in_at is not None and rejected_signed_in_at is not None:
        if int(tokens.signed_in_at) != int(rejected_signed_in_at):
            return
    elif rejected_access_token is not None and tokens.access_token != rejected_access_token:
        return
    if tokens.refresh_token:
        revoke_refresh_token(tokens.refresh_token)
    clear_tokens()


def refresh_access_token(tokens: StoredTokens) -> StoredTokens:
    """Use the stored refresh token to get a new access token. Everything else
    about the session — who signed in, and when — carries over."""
    config = get_config()

    response = httpx.post(
        f"https://{config.auth0_domain}/oauth/token",
        json={
            "grant_type": "refresh_token",
            "client_id": config.auth0_client_id,
            "refresh_token": tokens.refresh_token,
        },
    )

    if response.status_code != 200:
        console.print("[red]Token refresh failed. Please run: tl auth login[/red]")
        raise SystemExit(2)

    data = response.json()
    refreshed = StoredTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", tokens.refresh_token),
        expires_at=time.time() + data.get("expires_in", 3600),
        email=tokens.email,
        # A store from before the sign-in time was recorded gets it from the
        # token being replaced — the newest moment the session is known to be
        # at least as old as — so it is not exempt from sign-outs forever.
        signed_in_at=tokens.signed_in_at
        if tokens.signed_in_at is not None
        else signed_in_time(tokens.access_token),
    )
    save_tokens(refreshed)
    return refreshed


def revoke_refresh_token(refresh_token: str) -> bool:
    """Best-effort revocation of a refresh token at Auth0 (RFC 7009).

    Invalidates the long-lived credential server-side so it can no longer mint
    new access tokens. Public-client call — `client_id` only, no secret. Returns
    True on success; never raises — network / Auth0 errors are swallowed so
    `tl auth logout` can still clear the local credentials when offline.
    """
    config = get_config()
    try:
        response = httpx.post(
            f"https://{config.auth0_domain}/oauth/revoke",
            json={
                "client_id": config.auth0_client_id,
                "token": refresh_token,
            },
            timeout=10,
        )
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _exchange_code(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    config,
) -> StoredTokens:
    """Exchange authorization code for tokens."""
    response = httpx.post(
        f"https://{config.auth0_domain}/oauth/token",
        json={
            "grant_type": "authorization_code",
            "client_id": config.auth0_client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
    )

    if response.status_code != 200:
        console.print(f"[red]Token exchange failed: {response.text}[/red]")
        raise SystemExit(1)

    data = response.json()

    # Decode email from ID token if present
    email = None
    id_token = data.get("id_token")
    if id_token:
        email = _extract_email_from_jwt(id_token)

    return StoredTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=time.time() + data.get("expires_in", 3600),
        email=email,
        signed_in_at=signed_in_time(data["access_token"]),
    )


def _jwt_claims(token: str) -> dict:
    """The payload of a JWT without verification (already trusted from Auth0);
    empty when the string is not a JWT."""
    try:
        payload_part = token.split(".")[1]
        payload_part += "=" * (4 - len(payload_part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_part))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def _extract_email_from_jwt(token: str) -> str | None:
    email = _jwt_claims(token).get("email")
    return email if isinstance(email, str) else None


def signed_in_time(access_token: str) -> float | None:
    """When the session this token belongs to was signed in: the token's own
    issue time, on the issuer's clock — the same clock the platform compares it
    with — so a machine whose clock runs behind is not judged to have signed in
    before its last sign-out and locked out. None for a token without one: no
    sign-in time is sent, and the platform judges by the token alone, which is
    safer than a guess from this machine's clock."""
    iat = _jwt_claims(access_token).get("iat")
    if isinstance(iat, str):
        try:
            iat = float(iat)
        except ValueError:
            return None
    return float(iat) if isinstance(iat, int | float) and not isinstance(iat, bool) else None


def _start_callback_server(
    result: _CallbackResult,
    expected_state: str,
    port: int = 0,
    success_redirect: str | None = None,
) -> tuple[http.server.HTTPServer, int]:
    """Start a temporary HTTP server to receive the OAuth callback.

    On success the browser is redirected to `success_redirect` when given
    (the platform's sign-in, see `web_signin_url`), otherwise shown a static
    "you can close this tab" page. Failures always get the static page.
    """

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            # Check state
            received_state = params.get("state", [None])[0]
            if received_state != expected_state:
                result.error = "State mismatch — possible CSRF attack"
                self._respond("Login failed: state mismatch.")
                return

            if "error" in params:
                result.error = params["error"][0]
                desc = params.get("error_description", [""])[0]
                self._respond(f"Login failed: {desc or result.error}")
                return

            code = params.get("code", [None])[0]
            if not code:
                result.error = "No authorization code received"
                self._respond("Login failed: no code received.")
                return

            result.code = code
            if success_redirect:
                self.send_response(302)
                self.send_header("Location", success_redirect)
                self.end_headers()
                return
            self._respond(
                "Login successful! You can close this tab and return to the terminal."
            )

        def _respond(self, message: str):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = f"""<!DOCTYPE html>
<html><head><title>TL CLI Login</title></head>
<body style="font-family: system-ui; text-align: center; padding: 60px;">
<h2>{message}</h2>
</body></html>"""
            self.wfile.write(html.encode())

        def log_message(self, format, *args):
            pass  # Suppress HTTP logs

    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, port
