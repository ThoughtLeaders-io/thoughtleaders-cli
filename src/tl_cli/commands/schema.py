"""tl schema — Show raw-db schema documentation for `tl db pg|fb|es`."""

import json

import typer
from rich.console import Console
from rich.markdown import Markdown

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client

app = typer.Typer(help="Show schema documentation for raw db queries (`tl db pg|fb|es`)")
console = Console()


def _show(db: str, json_output: bool) -> None:
    client = get_client()
    try:
        data = client.get(f"/raw/{db}/schema")
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
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show PostgreSQL schema reference (for `tl db pg`)."""
    _show("pg", json_output)


@app.command("fb")
def fb_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show Firebolt schema (live: tables and column types) for `tl db fb`."""
    _show("fb", json_output)


@app.command("es")
def es_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show Elasticsearch document shape for `tl db es`."""
    _show("es", json_output)
