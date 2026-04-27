"""tl db — Run raw queries against PostgreSQL, Firebolt, or Elasticsearch."""

import json
import sys

import typer

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output

app = typer.Typer(help="Raw read-only queries against PostgreSQL, Firebolt, or Elasticsearch (full-access only)")


def _read_query(query: str | None) -> str:
    if query is not None and query != "-":
        return query
    if sys.stdin.isatty():
        raise typer.BadParameter("Provide a query argument or pipe one on stdin")
    return sys.stdin.read()


def _run(path: str, body: dict, fmt: str, title: str) -> None:
    client = get_client()
    try:
        data = client.post(path, json_body=body)
        output(data, fmt, title=title)
        aggs = data.get("aggregations")
        if aggs and fmt != "json":
            from rich.console import Console
            from rich.json import JSON
            console = Console()
            console.print("\n[bold]Aggregations[/bold]")
            console.print(JSON(json.dumps(aggs, default=str)))
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("pg")
def pg_cmd(
    query: str = typer.Argument(None, help="Raw PostgreSQL SELECT (or '-' to read from stdin)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output"),
) -> None:
    """Run a raw PostgreSQL SELECT query.

    Examples:
        tl db pg "SELECT id, name FROM thoughtleaders_brand LIMIT 10 OFFSET 0"
        cat query.sql | tl db pg -
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    sql = _read_query(query)
    _run("/raw/pg", {"query": sql}, fmt, "Postgres results")


@app.command("fb")
def fb_cmd(
    query: str = typer.Argument(None, help="Raw Firebolt SELECT (or '-' to read from stdin)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output"),
) -> None:
    """Run a raw Firebolt SELECT query.

    The query must filter the leading index column of the table (channel_id
    for article_metrics, id for channel_metrics) — see the Firebolt schema.

    Examples:
        tl db fb "SELECT scrape_date, view_count FROM article_metrics WHERE channel_id = 5607 AND id = 'EjeGzoQI3gQ'"
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    sql = _read_query(query)
    _run("/raw/fb", {"query": sql}, fmt, "Firebolt results")


@app.command("es")
def es_cmd(
    query: str = typer.Argument(None, help="Elasticsearch search body as JSON (or '-' to read from stdin)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output"),
) -> None:
    """Run a raw Elasticsearch search query.

    The index is fixed server-side; the client cannot select it.

    Examples:
        tl db es '{"size": 5, "query": {"term": {"channel.id": 5607}}}'
        tl db es '{"size": 0, "aggs": {"by_channel": {"terms": {"field": "channel.id"}}}}'
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    raw = _read_query(query)
    try:
        body_query = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Query is not valid JSON: {exc}") from exc

    _run("/raw/es", {"query": body_query}, fmt, "Elasticsearch results")
