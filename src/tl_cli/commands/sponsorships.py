"""tl sponsorships — List, show, and create sponsorships."""

import json as _json
from typing import Optional

import typer
from rich.console import Console

from tl_cli.client.errors import handle_api_error, ApiError
from tl_cli.client.http import get_client
from tl_cli.commands._comments_common import register_comment_commands
from tl_cli.filters import parse_filters
from tl_cli.hints import detail_hint
from tl_cli.output.formatter import detect_format, output, output_single

COLUMNS = ["sponsorship_id", "created_at", "brand_id", "brand", "channel_id", "channel", "article_id", "views", "impressions_guarantee", "status", "price", "cost", "cpm", "owner_sales_email"]
COLUMN_CONFIG = {
    "price": {"justify": "right"},
    "cost": {"justify": "right"},
    "views": {"justify": "right"},
    "impressions_guarantee": {"justify": "right"},
    "cpm": {"justify": "right"},
}


def _format_results(results: list[dict]) -> list[dict]:
    """Clean up sponsorship results for display."""
    for row in results:
        sd = row.get("send_date")
        if sd and isinstance(sd, str) and "T" in sd:
            row["send_date"] = sd[:10]
        for field in ("price", "cost", "impressions_guarantee"):
            val = row.get(field)
            if val is not None:
                try:
                    row[field] = str(int(float(val)))
                except (ValueError, TypeError):
                    pass
    return results


def do_list(
    args: list[str],
    fmt: str,
    limit: int,
    offset: int,
    *,
    default_status: str | None = None,
    title: str = "Sponsorships",
) -> None:
    """Shared list logic with optional default status filter."""
    filters = parse_filters(args)

    # Status values that are equivalent to each shortcut's default
    _EQUIVALENT_STATUSES = {
        "deal": {"deal", "sold"},
        "match": {"match", "matched"},
        "proposal": {"proposal", "proposed", "pending", "outreach"},
    }

    if default_status and "status" in filters:
        allowed = _EQUIVALENT_STATUSES.get(default_status, {default_status})
        if filters["status"] not in allowed:
            Console(stderr=True).print(
                f"[red]Error:[/red] The [bold]{title.lower()}[/bold] command does not accept status:{filters['status']}.\n"
                f"Use [bold]tl sponsorships list[/bold] for finer-grained status filtering."
            )
            raise typer.Exit(1)

    if default_status:
        filters.setdefault("status", default_status)

    client = get_client()
    try:
        params = {**filters, "limit": str(limit), "offset": str(offset)}
        data = client.get("/sponsorships", params=params)
        if "results" in data:
            data["results"] = _format_results(data["results"])
            for r in data["results"]:
                r["sponsorship_id"] = r.pop("id", None)
        output(data, fmt, columns=COLUMNS, title=title, column_config=COLUMN_CONFIG)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def do_show(item_id: str, fmt: str) -> None:
    """Shared show logic."""
    client = get_client()
    try:
        data = client.get(f"/sponsorships/{item_id}")
        for r in (data.get("results", []) if isinstance(data.get("results"), list) else []):
            r["sponsorship_id"] = r.pop("id", None)
        output_single(data, fmt)
        if fmt == "table" and data.get("show_cta"):
            record = data.get("results", data)
            if isinstance(record, list) and record:
                record = record[0]
            if isinstance(record, dict):
                hint = detail_hint(client, brand=record.get("brand"), channel=record.get("channel"))
                if hint:
                    Console(stderr=True).print(f"\n[yellow]{hint}[/yellow]")
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def do_create(
    channel: int,
    brand: int,
    price: float | None,
    fmt: str,
    status: str | None = None,
) -> None:
    """Shared create logic (flag-style args)."""
    body: dict = {"channel_id": channel, "brand_id": brand}
    if price is not None:
        body["price"] = price
    if status is not None:
        body["status"] = status
    do_create_body(body, fmt)


def do_create_body(body: dict, fmt: str) -> None:
    """Post a pre-built body to the sponsorships create endpoint."""
    client = get_client()
    try:
        data = client.post("/sponsorships", json_body=body)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


# --- Typer app ---

app = typer.Typer(help="Sponsorships (deals, matches, proposals)")


@app.callback(invoke_without_command=True)
def sponsorships(ctx: typer.Context) -> None:
    """Sponsorships — the centre of attention in ThoughtLeaders."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd, args=[], json_output=False, csv_output=False, md_output=False, limit=50, offset=0)


@app.command("list")
def list_cmd(
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs). Run 'tl describe show sponsorships' for available filters."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """List sponsorships with optional filters.

    Examples:
        tl sponsorships list                              # List recent sponsorships
        tl sponsorships list status:sold brand:"Nike"     # Filter sponsorships
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    do_list(args or [], fmt, limit, offset)


@app.command("show")
def show_cmd(
    item_id: str = typer.Argument(..., help="Sponsorship ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show sponsorship detail by ID.

    Examples:
        tl sponsorships show 12345
    """
    fmt = detect_format(json_output, False, False, toon_output)
    do_show(item_id, fmt)


@app.command("create")
def create_cmd(
    fields: Optional[str] = typer.Argument(
        None,
        help='Optional JSON body — alternative to --channel/--brand/--price flags. '
             'Shape: {"channel_id": int, "brand_id": int, "price"?: float, "status"?: str}. '
             'Mutually exclusive with the flag form.',
    ),
    channel: Optional[int] = typer.Option(None, "--channel", "-c", help="Channel ID"),
    brand: Optional[int] = typer.Option(None, "--brand", "-b", help="Brand ID"),
    price: Optional[float] = typer.Option(None, "--price", "-p", help="Deal price"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Create a new sponsorship proposal (free, no credits charged).

    Either pass --channel and --brand (with optional --price) as flags, or
    pass a JSON body as the positional argument — never both.

    Examples:
        tl sponsorships create --channel 1 --brand 2
        tl sponsorships create --channel 1 --brand 2 --price 2500
        tl sponsorships create '{"channel_id": 1, "brand_id": 2, "price": 2500}'
    """
    fmt = detect_format(json_output, False, False, toon_output)

    used_flags = channel is not None or brand is not None or price is not None
    if fields is not None and used_flags:
        Console(stderr=True).print(
            "[red]Error:[/red] Pass either a JSON body OR --channel/--brand/--price flags, not both."
        )
        raise typer.Exit(1)

    if fields is not None:
        try:
            body = _json.loads(fields)
        except _json.JSONDecodeError as e:
            Console(stderr=True).print(f"[red]Error:[/red] Invalid JSON body: {e}")
            raise typer.Exit(1)
        if not isinstance(body, dict):
            Console(stderr=True).print("[red]Error:[/red] JSON body must be an object.")
            raise typer.Exit(1)
        if "channel_id" not in body or "brand_id" not in body:
            Console(stderr=True).print(
                "[red]Error:[/red] JSON body must include channel_id and brand_id."
            )
            raise typer.Exit(1)
        body.setdefault("status", "proposed")
        do_create_body(body, fmt)
        return

    if channel is None or brand is None:
        Console(stderr=True).print(
            "[red]Error:[/red] --channel and --brand are required (or pass a JSON body)."
        )
        raise typer.Exit(1)
    do_create(channel, brand, price, fmt, status="proposed")


@app.command("update")
def update_cmd(
    sponsorship_id: int = typer.Argument(..., help="Sponsorship (adlink) ID"),
    fields: str = typer.Argument(..., help='JSON object of fields to update'),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Update a sponsorship.

    Unknown fields are rejected with a 400 listing the offending key.
    """
    fmt = detect_format(json_output, False, False, toon_output)
    try:
        body = _json.loads(fields)
    except _json.JSONDecodeError as exc:
        Console(stderr=True).print(f"[red]Error:[/red] fields argument must be a JSON object: {exc}")
        raise typer.Exit(1)
    if not isinstance(body, dict):
        Console(stderr=True).print("[red]Error:[/red] fields argument must be a JSON object.")
        raise typer.Exit(1)

    client = get_client()
    try:
        data = client.post(f"/sponsorships/{sponsorship_id}/edit", json_body=body)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


register_comment_commands(app, "sponsorship", "sponsorship")
