"""tl db — Run raw queries against PostgreSQL, Firebolt, or Elasticsearch."""

import json
import sys

import typer
from rich.console import Console

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output, output_pricing_estimate
from tl_cli.query_history import note_charge, query_hash, record_and_check

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Raw read-only queries against PostgreSQL, Firebolt, or Elasticsearch (full-access only)")

_err = Console(stderr=True)

_NO_REPEAT_WARNING_OPTION = typer.Option(
    False, "--no-repeat-warning",
    help=(
        "Suppress the warning shown when the same query is re-run repeatedly after "
        "burning 1000+ credits (also: TL_NO_REPEAT_WARNING=1)."
    ),
)


def _read_query(query: str | None) -> str:
    if query is not None and query != "-":
        return query
    if sys.stdin.isatty():
        raise typer.BadParameter("Provide a query argument or pipe one on stdin")
    return sys.stdin.read()


def _warn_if_repeat(digest: str, suppressed: bool) -> None:
    """Nudge (on stderr) when this exact query keeps being re-run AND the
    repeats have already burned a material amount of credits.

    Detection is local and best-effort; the query always executes. Cheap
    repeats stay silent — the warning only fires once the window's runs
    have been billed SPEND_THRESHOLD_CREDITS in total.
    """
    if suppressed:
        return
    due = record_and_check(digest)
    if due is None:
        return
    count, spent = due
    _err.print(
        f"[yellow]Repeat query:[/yellow] this exact query has now run {count} times "
        f"in the last 5 minutes ({spent:g} credits so far). Each run is billed and "
        "the results are unlikely to differ — reuse the earlier output (e.g. save it "
        "with `--json > file.json`). Pass --no-repeat-warning if the repeats are "
        "deliberate."
    )


def _run(path: str, body: dict, fmt: str, title: str, pricing: bool = False,
         digest: str | None = None) -> None:
    client = get_client()
    try:
        data = client.post(path, json_body=body)
        if digest:
            usage = data.get("usage") or {}
            note_charge(digest, usage.get("credits_charged"))
        if pricing:
            output_pricing_estimate(data, fmt)
            return
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
    pricing: bool = typer.Option(
        False, "--pricing",
        help="Estimate the query's credit cost via EXPLAIN without running it (flat 1 credit).",
    ),
    no_repeat_warning: bool = _NO_REPEAT_WARNING_OPTION,
) -> None:
    """Run a raw PostgreSQL SELECT query.

    Column names follow the current schema (e.g. subscribers, projected_views,
    scheduled_date — not the older reach / impression / send_date). Run
    `tl schema pg <table>` to see the exact columns your role can query.

    Examples:
        tl db pg "SELECT channel_name, subscribers, projected_views FROM thoughtleaders_channel ORDER BY subscribers DESC LIMIT 10"
        tl db pg "SELECT id, scheduled_date, publish_status FROM thoughtleaders_adlink LIMIT 20"
        cat query.sql | tl db pg -
        tl db pg "SELECT * FROM thoughtleaders_channel LIMIT 100" --pricing
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    sql = _read_query(query)
    digest = query_hash("pg", sql, pricing)
    _warn_if_repeat(digest, no_repeat_warning)
    body: dict = {"query": sql}
    if pricing:
        body["pricing"] = True
    _run("/raw/pg", body, fmt, "Postgres results", pricing=pricing, digest=digest)


@app.command("fb")
def fb_cmd(
    query: str = typer.Argument(None, help="Raw Firebolt SELECT (or '-' to read from stdin)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output"),
    pricing: bool = typer.Option(
        False, "--pricing",
        help="Estimate the query's credit cost without running it (flat 1 credit).",
    ),
    no_repeat_warning: bool = _NO_REPEAT_WARNING_OPTION,
) -> None:
    """Run a raw Firebolt SELECT query.

    Two tables: article_metrics (per-video daily metrics) and channel_metrics
    (per-channel history). Single-table SELECTs only (no JOINs), and WHERE
    must equality- or IN-filter the leading index column — channel_id for
    article_metrics, id (the channel id) for channel_metrics. Other columns
    can't be filtered server-side: fetch by the indexed key, then narrow
    client-side. Column names follow the current schema (subscribers, not
    the older reach) — run `tl schema fb` to see them.

    Examples:
        tl db fb "SELECT 1"   # connectivity check — the only no-FROM query allowed
        tl db fb "SELECT scrape_date, view_count FROM article_metrics WHERE channel_id = 5607 AND id = 'EjeGzoQI3gQ'"
        tl db fb "SELECT scrape_date, subscribers, total_views FROM channel_metrics WHERE id = 736006 ORDER BY scrape_date"
        tl db fb "SELECT publication_date, view_count FROM article_metrics WHERE channel_id IN (5607, 5608)"
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    sql = _read_query(query)
    digest = query_hash("fb", sql, pricing)
    _warn_if_repeat(digest, no_repeat_warning)
    body: dict = {"query": sql}
    if pricing:
        body["pricing"] = True
    _run("/raw/fb", body, fmt, "Firebolt results", pricing=pricing, digest=digest)


@app.command("es")
def es_cmd(
    query: str = typer.Argument(None, help="Elasticsearch search body as JSON (or '-' to read from stdin)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output"),
    pricing: bool = typer.Option(
        False, "--pricing",
        help="Estimate the query's credit cost without running it (flat 1 credit).",
    ),
    highlight: bool = typer.Option(
        False, "--highlight",
        help="Keep ES highlight fragments in each result row. Only meaningful when the query body includes a `highlight` clause; otherwise no-op.",
    ),
    no_repeat_warning: bool = _NO_REPEAT_WARNING_OPTION,
) -> None:
    """Run a raw Elasticsearch search query.

    The index is fixed server-side; the client cannot select it.

    Examples:
        tl db es '{"size": 5, "query": {"term": {"channel.id": 5607}}}'
        tl db es '{"size": 0, "aggs": {"by_channel": {"terms": {"field": "channel.id"}}}}'
        tl db es '{"query": {"match": {"transcript": "vpn"}}, "highlight": {"fields": {"transcript": {}}}}' --highlight
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    raw = _read_query(query)
    try:
        body_query = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Query is not valid JSON: {exc}") from exc

    digest = query_hash("es", raw, pricing)
    _warn_if_repeat(digest, no_repeat_warning)
    body: dict = {"query": body_query}
    if pricing:
        body["pricing"] = True
    if highlight:
        body["include_highlight"] = True
    _run("/raw/es", body, fmt, "Elasticsearch results", pricing=pricing, digest=digest)
