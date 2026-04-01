"""tl sponsorships — List, show, and create sponsorships."""

from typing import Optional

import typer
from rich.console import Console

from tl_cli.client.errors import handle_api_error, ApiError
from tl_cli.client.http import get_client
from tl_cli.filters import split_id_and_filters
from tl_cli.output.formatter import detect_format, output, output_single

COLUMNS = ["id", "brand", "channel", "status", "price", "send_date", "owner"]


def list_or_show(
    args: list[str],
    fmt: str,
    limit: int,
    offset: int,
    *,
    default_status: str | None = None,
    title: str = "Sponsorships",
) -> None:
    """Shared logic for listing/showing sponsorships with an optional default status filter."""
    item_id, filters = split_id_and_filters(args)

    if default_status and "status" in filters:
        Console(stderr=True).print(
            f"[red]Error:[/red] The [bold]{title.lower()}[/bold] command does not accept a status filter.\n"
            f"Use [bold]tl sponsorships[/bold] for finer-grained status filtering."
        )
        raise typer.Exit(1)

    if default_status and not item_id:
        filters.setdefault("status", default_status)

    client = get_client()
    try:
        if item_id:
            data = client.get(f"/sponsorships/{item_id}")
            output_single(data, fmt)
        else:
            params = {**filters, "limit": str(limit), "offset": str(offset)}
            data = client.get("/sponsorships", params=params)
            output(data, fmt, columns=COLUMNS, title=title)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


app = typer.Typer(help="Sponsorships (deals, matches, proposals)")


@app.callback(invoke_without_command=True)
def sponsorships(
    ctx: typer.Context,
    args: list[str] = typer.Argument(None, help="ID or filters (key:value pairs)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """List sponsorships or show a single sponsorship by ID.

    Examples:
        tl sponsorships                              # List recent sponsorships
        tl sponsorships 12345                        # Show sponsorship #12345
        tl sponsorships status:sold brand:"Nike"     # Filter sponsorships
    """
    if ctx.invoked_subcommand is not None:
        return

    fmt = detect_format(json_output, csv_output, md_output, quiet)
    list_or_show(args or [], fmt, limit, offset)


@app.command("create")
def create(
    channel: int = typer.Option(..., "--channel", "-c", help="Channel ID"),
    brand: int = typer.Option(..., "--brand", "-b", help="Brand ID"),
    price: Optional[float] = typer.Option(None, "--price", "-p", help="Deal price"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON only"),
) -> None:
    """Create a new sponsorship proposal (free, no credits charged)."""
    fmt = detect_format(json_output, False, False, quiet)
    body = {"channel_id": channel, "brand_id": brand}
    if price is not None:
        body["price"] = price

    client = get_client()
    try:
        data = client.post("/sponsorships", json_body=body)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
