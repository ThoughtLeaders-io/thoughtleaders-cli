"""tl balance — Show credit balance and recent usage."""

import json

import typer
from tl_cli._typer_utils import AlphaSortedTyperGroup
from rich.console import Console
from rich.table import Table

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Credit balance and usage (free)")
console = Console()


@app.callback(invoke_without_command=True)
def balance(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show your credit balance and recent usage (free, no credits).

    Examples:
        tl balance
        tl balance --json
    """
    if ctx.invoked_subcommand is not None:
        return

    fmt = detect_format(json_output, False, False, toon_output)

    client = get_client()
    try:
        data = client.get("/balance")

        if fmt == "json":
            print(json.dumps(data, indent=2, default=str))
            return

        balance_val = data.get("balance", 0)
        allow_overage = data.get("allow_overage", False)

        console.print(f"\n[bold]Credit Balance:[/bold] [cyan]{balance_val}[/cyan] credits")
        # Older servers return only the combined balance; newer ones split it
        # into the plan-granted (top-up) pool and the purchased pool.
        topup_val = data.get("topup_balance")
        purchased_val = data.get("purchased_balance")
        if topup_val is not None and purchased_val is not None:
            console.print(f"[dim]Plan (top-up) credits: {topup_val} · Purchased: {purchased_val}[/dim]")
        if allow_overage:
            console.print("[dim]Overage: enabled[/dim]")

        # Top-up hint when running low. Threshold matches the hook warning
        # that nudges the user before they hit 0.
        try:
            balance_decimal = float(balance_val)
        except (TypeError, ValueError):
            balance_decimal = None
        if balance_decimal is not None and balance_decimal < 500:
            console.print(
                "[yellow]Running low.[/yellow] Top up with: "
                "[bold]tl credits buy --amount-usd 10[/bold] "
                "(or https://app.thoughtleaders.io/billing/cli)"
            )

        recent = data.get("recent_usage", [])
        if recent:
            table = Table(title="Recent Usage")
            table.add_column("Date")
            table.add_column("Resource")
            table.add_column("Results", justify="right")
            table.add_column("Credits", justify="right")
            for entry in recent[:10]:
                table.add_row(
                    entry.get("date", ""),
                    entry.get("resource", ""),
                    str(entry.get("results_count", "")),
                    str(entry.get("credits_charged", "")),
                )
            console.print(table)

    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
