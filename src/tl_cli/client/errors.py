"""User-friendly error handling for API responses."""

import json
import sys
import traceback

from rich.console import Console

err = Console(stderr=True)


class ApiError(Exception):
    """Raised when the API returns a non-success status."""

    def __init__(self, status_code: int, detail: str, raw: dict | None = None, url: str | None = None, response_text: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.raw = raw
        self.url = url
        self.response_text = response_text
        super().__init__(f"HTTP {status_code}: {detail}")


def _print_debug(error: ApiError) -> None:
    """Print detailed debug info for an API error."""
    from tl_cli.config import debug

    if not debug:
        return
    err.print(f"\n[dim]--- debug ---[/dim]")
    if error.url:
        err.print(f"[dim]URL: {error.url}[/dim]")
    err.print(f"[dim]HTTP {error.status_code}: {error.detail}[/dim]")
    if error.response_text:
        err.print(f"[dim]Response body:[/dim]")
        err.print(f"[dim]{error.response_text}[/dim]")
    err.print(f"[dim]Traceback:[/dim]")
    err.print(f"[dim]{''.join(traceback.format_exception(error))}[/dim]")


def handle_api_error(error: ApiError) -> None:
    """Print a user-friendly error message and exit with the right code."""
    if error.status_code == 401:
        err.print("[red]Authentication required.[/red] Run: tl auth login")
        _print_debug(error)
        sys.exit(2)
    elif error.status_code == 402:
        err.print("[red]Insufficient credits.[/red]")
        err.print("Top up with: [bold]tl credits buy --amount-usd 10[/bold]")
        err.print("Or visit: https://app.thoughtleaders.io/billing/cli")
        _print_debug(error)
        sys.exit(4)
    elif error.status_code == 403:
        err.print(f"[red]Access denied:[/red] {error.detail}")
        err.print("Your plan may not include access to this resource.")
        _print_debug(error)
        sys.exit(1)
    elif error.status_code == 404:
        err.print(f"[yellow]Not found:[/yellow] {error.detail}")
        _print_debug(error)
        sys.exit(1)
    elif error.status_code == 429:
        # Both quota gates refuse with 429 and compose the whole explanation
        # into `detail` — which cap was hit, how much of it is used, and when it
        # frees up. Collapsing that to a flat "rate limited" line drops the only
        # thing that tells the user whether to wait, buy credits, or ask for a
        # seat. An edge/WAF 429 carries no detail and keeps the generic wording.
        if _print_no_seat(error):
            pass
        elif error.detail:
            err.print(f"[yellow]{error.detail}[/yellow]")
        else:
            err.print("[yellow]Rate limited.[/yellow] Please wait and try again.")
        _print_debug(error)
        sys.exit(3)
    elif error.status_code >= 500:
        err.print(f"[red]Server error ({error.status_code}):[/red] {error.detail}")
        _print_debug(error)
        sys.exit(3)
    else:
        detail = error.detail or ""
        hint = (error.raw or {}).get("hint") if isinstance(error.raw, dict) else None
        if isinstance(hint, str) and hint:
            # The server sends the remediation both concatenated into
            # `detail` (for older clients) and as a separate `hint` key —
            # render it on its own line so it can't get lost in the error.
            if detail.endswith(hint):
                detail = detail[: -len(hint)].rstrip()
            err.print(f"[red]Error ({error.status_code}):[/red] {detail}")
            err.print(f"[bold yellow]Hint:[/bold yellow] [yellow]{hint}[/yellow]")
        else:
            err.print(f"[red]Error ({error.status_code}):[/red] {detail}")
        _print_debug(error)
        sys.exit(1)


def _print_no_seat(error: ApiError) -> bool:
    """Render the seatless refusal as its own thing, or return False.

    The server already composes a complete sentence for this case and the 429
    branch above would print it — but when several people can grant the seat
    they arrive as a comma-run inside one long line, which is the least legible
    shape for the only part the reader has to act on. The refusal also carries
    them structurally (`_billing_seat_admins`), so they can be listed instead.

    Everything else about the 429 path is deliberately left alone: the server
    owns the wording, and this must not become a second place that composes it.
    """
    raw = error.raw if isinstance(error.raw, dict) else {}
    admins = raw.get("_billing_seat_admins")
    # Only worth taking over when there is actually a list to lay out; a
    # single-contact or self-serve refusal reads fine as the server's sentence.
    if not raw.get("_billing_no_seat") or not isinstance(admins, list) or len(admins) < 2:
        return False
    err.print(
        "[yellow]No CLI seat.[/yellow] Your organization is on a paid plan, "
        "but your user isn't assigned to a seat."
    )
    err.print("Ask an owner or admin on your team to assign you one:")
    for a in admins:
        if not isinstance(a, dict):
            continue
        name = a.get("name") or a.get("email") or "?"
        role = a.get("role") or ""
        err.print(f"  · {name} <{a.get('email', '')}>" + (f" [dim]({role})[/dim]" if role else ""))
    url = raw.get("_billing_seats_url")
    if url:
        err.print(f"Seats are managed at: [bold]{url}[/bold]")
    return True
