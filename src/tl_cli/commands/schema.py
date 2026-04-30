"""tl schema — Show raw-db schema documentation for `tl db pg|fb|es`."""

import json

import typer
from rich.console import Console
from rich.markdown import Markdown

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client

app = typer.Typer(help="Show schema documentation for raw db queries (`tl db pg|fb|es`)")
console = Console()


def _show(db: str, json_output: bool, table: str | None = None) -> None:
    client = get_client()
    try:
        params = {"table": table} if table else {}
        data = client.get(f"/raw/{db}/schema", params=params)
        if json_output:
            print(json.dumps(data, indent=2, default=str))
            return
        content = data.get("content", "")
        if console.is_terminal:
            console.print(Markdown(content))
        else:
            print(content)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("pg")
def pg_cmd(
    table: str = typer.Argument(None, help="Optional table name. When given, prints only that table's section in the same markdown format."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show PostgreSQL schema reference (for `tl db pg`).

    With no argument: lists every table visible to your role.
    With a table name: prints only that table's column listing.

    **Strongly preferred for single-table lookups.** Listing every
    table just to read one is wasteful — pass the table name and the
    server returns only that section.

    Examples:
        tl schema pg
        tl schema pg thoughtleaders_channel
        tl schema pg thoughtleaders_adlink --json
    """
    _show("pg", json_output, table=table)


@app.command("fb")
def fb_cmd(
    table: str = typer.Argument(None, help="Optional table name (`article_metrics` or `channel_metrics`). When given, prints only that table's section."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show Firebolt schema (live: tables and column types) for `tl db fb`.

    With no argument: lists both accepted tables.
    With a table name: prints only that table's columns + primary index.

    **Strongly preferred for single-table lookups.** Pass the table
    name to skip the other one.

    Examples:
        tl schema fb
        tl schema fb article_metrics
        tl schema fb channel_metrics --json
    """
    _show("fb", json_output, table=table)


@app.command("es")
def es_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show Elasticsearch document shape for `tl db es`."""
    _show("es", json_output)
