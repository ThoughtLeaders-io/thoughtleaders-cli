"""tl resets — banked usage resets: list them and spend one.

A usage reset refills your weekly credits to your plan's allotment and
restarts your 5-hour session. Spending one is always your explicit choice.
"""

import json
import sys
from datetime import datetime

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Usage resets: list them and spend one (free)")
console = Console()
err = Console(stderr=True)

SOURCE_LABELS = {
    "welcome": "Welcome reset",
    "referred_bonus": "You were invited",
    "referral_signup": "Your invite was accepted",
    "referral_bonus": "Your invitee's first proposal or payment",
    "admin_grant": "Added by support",
}

STATUS_LABELS = {
    "issued": "Available",
    "used": "Used",
    "expired": "Expired",
    "capped": "Over the limit",
    "voided": "Removed",
}

# Refusals of `tl resets use`. None of them consume a reset; the server's
# `detail` says why, so it is shown as is.
REFUSAL_CODES = {"nothing_to_restore", "reset_not_eligible", "resets_disabled", "no_reset_available"}

DISABLED_MESSAGE = "Usage resets aren't available on your account."
HISTORY_LIMIT = 10


def _label(mapping: dict[str, str], value: str | None) -> str:
    return mapping.get(value or "", value or "")


def _day(value: str | None) -> str:
    """An ISO timestamp as its calendar date; anything unparseable as is."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _interactive() -> bool:
    return sys.stdin.isatty()


def _render_resets(data: dict) -> None:
    if not data.get("enabled"):
        console.print(DISABLED_MESSAGE)
        return

    available = data.get("available") or []
    console.print(f"\n[bold]Usage resets available:[/bold] [cyan]{len(available)}[/cyan]")
    console.print(
        "[dim]A reset refills your weekly credits to your plan's allotment "
        "and restarts your 5-hour session.[/dim]"
    )
    if not data.get("eligible", True):
        console.print("[yellow]Resets can't be spent on your current plan.[/yellow]")

    if available:
        table = Table(title="Available")
        table.add_column("Reason")
        table.add_column("Expires")
        for reset in available:
            table.add_row(_label(SOURCE_LABELS, reset.get("source")), _day(reset.get("expires_at")))
        console.print(table)
        if data.get("eligible", True):
            console.print("Spend one with: [bold]tl resets use[/bold]")

    history = data.get("history") or []
    if history:
        table = Table(title="Recent history")
        table.add_column("Reason")
        table.add_column("Status")
        table.add_column("Granted")
        table.add_column("Used / expires")
        for reset in history[:HISTORY_LIMIT]:
            when = reset.get("used_at") if reset.get("status") == "used" else reset.get("expires_at")
            table.add_row(
                _label(SOURCE_LABELS, reset.get("source")),
                _label(STATUS_LABELS, reset.get("status")),
                _day(reset.get("granted_at")),
                _day(when),
            )
        console.print(table)

    link = data.get("referral_link")
    if link:
        console.print(f"\n[bold]Your invite link:[/bold] {escape(link)}")
        bonus = data.get("bonus_resets")
        earn = "You earn a reset for each new organization that signs up with it"
        if bonus:
            earn += f", and {_plural(bonus, 'more reset')} when it makes its first proposal or payment"
        console.print(f"[dim]{earn}.[/dim]")

    referrals = data.get("referrals") or {}
    made = referrals.get("made") or 0
    valid = referrals.get("valid") or 0
    if made:
        console.print(f"{_plural(made, 'user')} signed up with your link")
    if valid:
        console.print(f"{_plural(valid, 'user')} earned you a reset")

    expiry_days = data.get("expiry_days")
    if expiry_days:
        console.print(f"[dim]Resets expire {expiry_days} days after they're granted.[/dim]")


def _render_use(result: dict) -> None:
    console.print("[green]Usage reset spent.[/green]")
    console.print(
        f"Weekly credits: {result.get('weekly_before')} → "
        f"[cyan]{result.get('weekly_after')}[/cyan] credits"
    )
    if result.get("session_reanchored"):
        console.print("Your 5-hour session restarted.")
    left = result.get("available")
    if left is not None:
        console.print(f"Resets left: [cyan]{left}[/cyan]")


@app.callback(invoke_without_command=True)
def resets(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show your usage resets, your invite link and referrals (free, no credits).

    Examples:
        tl resets
        tl resets --json
        tl resets use
    """
    if ctx.invoked_subcommand is not None:
        return

    fmt = detect_format(json_output, False, False)
    client = get_client()
    try:
        data = client.get("/resets")
    except ApiError as e:
        handle_api_error(e)
        return
    finally:
        client.close()

    if fmt == "json":
        print(json.dumps(data, indent=2, default=str))
        return
    _render_resets(data)


@app.command("use")
def use_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Spend without asking for confirmation"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Spend one usage reset (the one that expires first).

    Refills your weekly credits to your plan's allotment and restarts your
    5-hour session. Asks for confirmation unless --yes is passed or the
    session isn't interactive.

    Examples:
        tl resets use
        tl resets use --yes --json
    """
    fmt = detect_format(json_output, False, False)
    if not yes and _interactive():
        if not typer.confirm(
            "Spend one usage reset? It refills your weekly credits and restarts your 5-hour session.",
            err=True,
        ):
            err.print("No reset spent.")
            raise typer.Exit(1)

    client = get_client()
    try:
        result = client.post("/resets/use")
    except ApiError as e:
        code = e.raw.get("code") if isinstance(e.raw, dict) else None
        if code in REFUSAL_CODES:
            err.print(f"[yellow]{escape(e.detail)}[/yellow]")
            raise typer.Exit(5 if e.status_code == 403 else 1)
        handle_api_error(e)
        return
    finally:
        client.close()

    if fmt == "json":
        print(json.dumps(result, indent=2, default=str))
        return
    _render_use(result)
