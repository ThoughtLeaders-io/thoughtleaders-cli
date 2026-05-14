"""tl credits — buy credits and view top-up history.

`tl credits buy --amount-usd N` calls the server to start a top-up,
opens the resulting web checkout URL in the user's browser, and polls
the balance until it changes (or the user gives up).

`tl credits history` lists recent top-ups for the caller's org.

`tl credits pricing` shows the current usd-per-credit rate. Use this to
sanity-check what `--amount-usd N` will buy before paying.
"""

from __future__ import annotations

import json
import time
import webbrowser
from decimal import Decimal, InvalidOperation

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format

app = typer.Typer(help="Buy credits and view top-up history (free)")
console = Console()
err = Console(stderr=True)


@app.command("pricing")
def pricing_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show the credit-to-USD rate, minimum purchase, and starter balance.

    Free — no authentication required.
    """
    client = get_client()
    try:
        data = client.get("/pricing")
    except ApiError as e:
        handle_api_error(e)
        return
    finally:
        client.close()

    if json_output:
        print(json.dumps(data, indent=2, default=str))
        return

    console.print(f"\n[bold]Rate:[/bold] ${data['usd_per_credit']} per credit ({data.get('currency', 'USD')})")
    console.print(f"[bold]Minimum top-up:[/bold] ${data['min_purchase_usd']}")
    console.print(f"[bold]Starter balance:[/bold] {data['starter_balance']} credits")


@app.command("buy")
def buy_cmd(
    amount_usd: str = typer.Option(..., "--amount-usd", help="Amount to top up, in USD."),
    poll: bool = typer.Option(True, "--poll/--no-poll", help="Poll balance after opening the checkout page."),
) -> None:
    """Start a credit top-up.

    Calls the server to create a pending purchase, prints the checkout URL,
    then asks whether to open it in a browser. Polls `tl balance` (unless
    `--no-poll`) until the credits land or you Ctrl-C out.
    """
    try:
        Decimal(amount_usd)
    except (InvalidOperation, ValueError):
        err.print(f"[red]Invalid amount:[/red] {amount_usd}")
        raise typer.Exit(1)

    client = get_client()
    try:
        try:
            initial = client.get("/balance")
            initial_balance = Decimal(str(initial.get("balance", 0)))
        except ApiError:
            # Pricing fetch may work even if balance fails; still attempt the purchase.
            initial_balance = None

        try:
            result = client.post("/top-up", {"usd_amount": amount_usd})
        except ApiError as e:
            handle_api_error(e)
            return
    finally:
        client.close()

    checkout_url = result.get("checkout_url")
    credits = result.get("credits")
    console.print(
        f"\n[bold]Started top-up:[/bold] ${result['usd_amount']} → {credits} credits"
    )
    if checkout_url:
        console.print(f"[bold]Checkout URL:[/bold] {checkout_url}\n")
        console.print("How would you like to continue?")
        console.print("  [cyan]1[/cyan] — Open the URL in a browser on this machine (default)")
        console.print("  [cyan]2[/cyan] — I'll open it manually")
        choice = Prompt.ask("Choose", choices=["1", "2"], default="1", console=console)
        if choice == "1":
            try:
                webbrowser.open(checkout_url)
            except Exception:
                console.print("[yellow]Could not launch a browser. Open the URL above manually.[/yellow]")

    if not poll or initial_balance is None:
        console.print("[dim]Run `tl balance` to confirm once payment completes.[/dim]")
        return

    _poll_for_credit(initial_balance, expected_increment=Decimal(str(credits)))


def _poll_for_credit(initial_balance: Decimal, expected_increment: Decimal) -> None:
    """Poll the balance endpoint until it goes up. Bounded so the CLI
    eventually returns to the prompt instead of hanging forever.
    """
    console.print("[dim]Polling balance every 5s for up to 10 minutes (Ctrl-C to stop)…[/dim]")
    deadline = time.time() + 600
    last_balance = initial_balance
    try:
        while time.time() < deadline:
            time.sleep(5)
            client = get_client()
            try:
                data = client.get("/balance")
            except ApiError:
                client.close()
                continue
            client.close()
            new_balance = Decimal(str(data.get("balance", 0)))
            if new_balance >= initial_balance + expected_increment:
                console.print(f"[green]Payment confirmed.[/green] New balance: [cyan]{new_balance}[/cyan] credits")
                return
            if new_balance != last_balance:
                console.print(f"[dim]Balance updated: {new_balance} credits[/dim]")
                last_balance = new_balance
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped polling.[/yellow] Run `tl balance` later to check.")
        return
    console.print("[yellow]Timed out waiting for payment.[/yellow] Run `tl balance` later to check.")


@app.command("history")
def history_cmd(
    limit: int = typer.Option(25, "--limit", help="Max rows to show"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show recent credit top-ups for your organization (free)."""
    fmt = detect_format(json_output, False, False, False)
    client = get_client()
    try:
        data = client.get("/credit-purchases", params={"limit": limit, "offset": offset})
    except ApiError as e:
        handle_api_error(e)
        return
    finally:
        client.close()

    if fmt == "json":
        print(json.dumps(data, indent=2, default=str))
        return

    rows = data.get("results", [])
    if not rows:
        console.print("[dim]No credit purchases yet. Run `tl credits buy --amount-usd N`.[/dim]")
        return

    table = Table(title=f"Credit purchases ({data.get('total', len(rows))} total)")
    table.add_column("Date")
    table.add_column("USD", justify="right")
    table.add_column("Credits", justify="right")
    table.add_column("Status")
    table.add_column("Invoice")
    for row in rows:
        table.add_row(
            row.get("created_at", "")[:19].replace("T", " "),
            row.get("usd_amount", ""),
            row.get("credits", ""),
            row.get("status", ""),
            row.get("green_invoice_document_id") or "—",
        )
    console.print(table)
