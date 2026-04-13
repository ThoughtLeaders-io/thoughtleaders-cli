"""tl brands — Brand intelligence reports."""

import typer
from rich.console import Console

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.filters import parse_filters
from tl_cli.output.formatter import detect_format, output

app = typer.Typer(help="Brand intelligence (sponsorship activity, channel mentions)")
err_console = Console(stderr=True)

COLUMNS = ["channel", "mentions", "type", "latest_date", "views"]
COLUMN_CONFIG = {"mentions": {"justify": "right"}, "views": {"justify": "right"}}

LIST_COLUMNS = ["name", "category", "channels", "sponsorships", "latest_activity"]


def _format_results(results: list[dict]) -> list[dict]:
    """Clean up brand results for display."""
    for row in results:
        ld = row.get("latest_date")
        if ld and isinstance(ld, str) and "T" in ld:
            row["latest_date"] = ld[:10]
    return results


def _validate_show_args(
    query: str,
    limit: int,
    offset: int,
    channel: int | None,
) -> None:
    """Validate show command arguments. Prints error and exits on failure."""
    if not query.strip():
        err_console.print("[red]Error:[/red] Brand name cannot be empty.")
        raise typer.Exit(1)
    if limit < 1 or limit > 200:
        err_console.print("[red]Error:[/red] --limit must be between 1 and 200.")
        raise typer.Exit(1)
    if offset < 0:
        err_console.print("[red]Error:[/red] --offset must be 0 or greater.")
        raise typer.Exit(1)
    if channel is not None and channel < 1:
        err_console.print("[red]Error:[/red] --channel must be a positive integer.")
        raise typer.Exit(1)


def _validate_list_args(limit: int, offset: int) -> None:
    """Validate list command arguments. Prints error and exits on failure."""
    if limit < 1 or limit > 200:
        err_console.print("[red]Error:[/red] --limit must be between 1 and 200.")
        raise typer.Exit(1)
    if offset < 0:
        err_console.print("[red]Error:[/red] --offset must be 0 or greater.")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def brands(ctx: typer.Context) -> None:
    """Brand intelligence — sponsorship activity and channel mentions."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd, args=[], json_output=False, csv_output=False, md_output=False, quiet=False, limit=50, offset=0)


@app.command("list")
def list_cmd(
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """Search and browse brands with optional filters.

    Examples:
        tl brands list                                # List brands
        tl brands list category:tech                  # Filter by category
        tl brands list name:"Hello Fresh"             # Search by name
    """
    _validate_list_args(limit, offset)
    fmt = detect_format(json_output, csv_output, md_output, quiet)
    filters = parse_filters(args or [])

    client = get_client()
    try:
        params = {**filters, "limit": str(limit), "offset": str(offset)}
        data = client.get("/brands", params=params)
        output(
            data,
            fmt,
            columns=LIST_COLUMNS,
            title="Brands",
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("show")
def show_cmd(
    query: str = typer.Argument(..., help="Brand name to research"),
    channel: int | None = typer.Option(None, "--channel", "-c", help="Filter to a specific channel"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """Research a brand's sponsorship activity and channel mentions.

    Requires an Intelligence plan.

    Examples:
        tl brands show Nike                          # Nike's sponsorship intelligence
        tl brands show Nike --channel 12345          # Nike mentions on a specific channel
    """
    _validate_show_args(query, limit, offset, channel)
    fmt = detect_format(json_output, csv_output, md_output, quiet)

    params: dict[str, str] = {"limit": str(limit), "offset": str(offset)}
    if channel is not None:
        params["channel_id"] = str(channel)

    client = get_client()
    try:
        data = client.get(f"/brands/{query}", params=params)
        if "results" in data:
            data["results"] = _format_results(data["results"])
        output(
            data,
            fmt,
            columns=COLUMNS,
            title=f"Brand Intelligence: {query}",
            column_config=COLUMN_CONFIG,
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
