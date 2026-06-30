"""tl brands — Brand detail, find, and similar-brand recommendations.

The `history` / `history-stats` subcommands are deprecated; equivalent
queries run against `tl db es` (`sponsored_brand_mentions`) joined to
`tl db pg` for channel/brand names.
"""

import urllib.parse

import typer
from rich.console import Console

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.commands._comments_common import register_comment_commands
from tl_cli.filters import parse_filters
from tl_cli.hints import detail_hint
from tl_cli.output.formatter import detect_format, output, output_single

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Brand intelligence (detail, find, similar)")
register_comment_commands(app, "brand", "brand")


_HISTORY_DEPRECATION = (
    "[deprecation] `tl brands history` is deprecated and will be removed. "
    "Use `tl db es` on docs with `sponsored_brand_mentions: <brand_id>` and "
    "join channel names from `thoughtleaders_channel` via `tl db pg`."
)
_HISTORY_STATS_DEPRECATION = (
    "[deprecation] `tl brands history-stats` is deprecated and will be removed. "
    "Use a `tl db es` aggregation over `sponsored_brand_mentions: <brand_id>`."
)


def _warn_deprecated(message: str) -> None:
    Console(stderr=True).print(f"[yellow]{message}[/yellow]")


@app.callback(invoke_without_command=True)
def brands(ctx: typer.Context) -> None:
    """Brands — detail, find, similar."""
    if ctx.invoked_subcommand is None:
        ctx.get_help()
        raise typer.Exit()


def _handle_brand_api_error(e: ApiError) -> None:
    """Print a candidates list for ambiguous brand name matches."""
    if e.status_code == 400 and isinstance(e.raw, dict) and e.raw.get("candidates"):
        err = Console(stderr=True)
        err.print(f"[yellow]{e.detail}[/yellow]")
        err.print()
        err.print("[bold]Candidates:[/bold]")
        err.print(f"  {'brand_id':>10}  {'website':<30}  name")
        err.print(f"  {'-' * 10}  {'-' * 30}  {'-' * 40}")
        for c in e.raw["candidates"]:
            err.print(f"  {c['brand_id']:>10}  {c.get('website', ''):<30}  {c['name']}")
        raise typer.Exit(1)
    handle_api_error(e)


@app.command("show")
def show_cmd(
    query: str = typer.Argument(..., help="Brand name or numeric ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output (flattens nested fields)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show brand detail by name or ID.

    Accepts either a numeric brand ID or a partial name. Names that
    match more than one brand return an error with candidate IDs.

    Examples:
        tl brands show Nike
        tl brands show 21416
    """
    fmt = detect_format(json_output, csv_output, False, toon_output)
    encoded_query = urllib.parse.quote(query, safe="")
    client = get_client()
    try:
        data = client.get(f"/brands/{encoded_query}")
        for r in data.get("results", []) if isinstance(data.get("results"), list) else []:
            r["brand_id"] = r.pop("id", None)
        output_single(data, fmt)
        if fmt == "table" and data.get("show_cta"):
            record = data.get("results", data)
            if isinstance(record, list) and record:
                record = record[0]
            if isinstance(record, dict):
                hint = detail_hint(client, brand=record.get("name"))
                if hint:
                    Console(stderr=True).print(f"\n[yellow]{hint}[/yellow]")
    except ApiError as e:
        _handle_brand_api_error(e)
    finally:
        client.close()


@app.command("history", deprecated=True)
def history_cmd(
    query: str = typer.Argument(..., help="Brand name or numeric ID"),
    channel: int | None = typer.Option(None, "--channel", "-c", help="Filter to a specific channel"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """Deprecated. Show a brand's sponsorship history (videos where the brand was detected).

    Prefer a raw `tl db es` probe on `sponsored_brand_mentions` (joined to
    `thoughtleaders_channel` via `tl db pg` for channel names). See
    `skills/tl/SKILL.md` → "Brand sponsorship history" for the canonical
    pattern. Requires an Intelligence plan.
    """
    _warn_deprecated(_HISTORY_DEPRECATION)
    fmt = detect_format(json_output, csv_output, md_output, toon_output)

    params: dict[str, str] = {"limit": str(limit), "offset": str(offset)}
    if channel is not None:
        params["channel_id"] = str(channel)

    encoded_query = urllib.parse.quote(query, safe="")
    client = get_client()
    try:
        data = client.get(f"/brands/{encoded_query}/history", params=params)
        brand_name = data.get("brand", {}).get("name", query)
        output(
            data,
            fmt,
            columns=["video_id", "title", "channel_id", "channel", "views", "publication_date", "is_tl"],
            title=f"Brand History: {brand_name}",
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("history-stats", deprecated=True)
def history_stats_cmd(
    query: str = typer.Argument(..., help="Brand name or numeric ID"),
    channel: int | None = typer.Option(None, "--channel", "-c", help="Restrict the roll-up to a specific channel"),
    top_channels: int = typer.Option(10, "--top-channels", help="How many top-by-count channels to include in the roll-up (1-50)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Deprecated. Aggregate roll-up of a brand's sponsorship history (no per-row output).

    Prefer a `tl db es` aggregation over `sponsored_brand_mentions: <brand_id>`
    for totals / per-year buckets / top channels. Requires an Intelligence
    plan. Costs 5 credits flat.
    """
    _warn_deprecated(_HISTORY_STATS_DEPRECATION)
    fmt = detect_format(json_output, csv_output, md_output, toon_output)

    params: dict[str, str] = {"top-channels": str(top_channels)}
    if channel is not None:
        params["channel_id"] = str(channel)

    encoded_query = urllib.parse.quote(query, safe="")
    client = get_client()
    try:
        data = client.get(f"/brands/{encoded_query}/history-stats", params=params)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("find")
def find_cmd(
    query: str = typer.Argument(..., help="Brand name, slug, domain, or keyword"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Resolve a string to a single brand.

    Searches across name, slug, website domain, and the brand's keyword
    fields (kw + keywords). Default output is a pretty `id  name` line on
    stdout; pass --json / --csv / --md / --toon for machine-readable
    output (the JSON shape is `{"id": ..., "name": ...}`).

    Ambiguous matches return an error with the candidate IDs and names so
    the caller can pick a better query.

    Examples:
        tl brands find Nike
        tl brands find nike.com
        tl brands find https://www.nike.com/
        tl brands find 21416
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    client = get_client()
    try:
        data = client.get("/brands/find", params={"q": query})
        results = data.get("results", [])
        record = results[0] if results else {}
        if fmt == "table":
            bid = record.get("id")
            name = record.get("name")
            if bid is None:
                Console(stderr=True).print("[yellow]No match.[/yellow]")
                raise typer.Exit(1)
            Console().print(f"[bold yellow]{bid}[/bold yellow]  {name}")
        else:
            output(
                {"results": [{"id": record.get("id"), "name": record.get("name")}]},
                fmt,
                columns=["id", "name"],
                title=f"Brand match for {query}",
            )
    except ApiError as e:
        if e.status_code == 400 and isinstance(e.raw, dict) and e.raw.get("candidates"):
            if fmt == "table":
                _print_brand_find_candidates(e.detail, e.raw["candidates"])
            else:
                # Machine-readable output: emit candidates through the
                # standard formatter so --json / --csv / --md / --toon all
                # produce the same structural surface the success path uses.
                Console(stderr=True).print(f"[yellow]{e.detail}[/yellow]")
                output(
                    {"detail": e.detail, "results": e.raw["candidates"]},
                    fmt,
                    columns=["id", "name", "website"],
                    title="Ambiguous match — candidates",
                )
            raise typer.Exit(1)
        handle_api_error(e)
    finally:
        client.close()


def _print_brand_find_candidates(detail: str, candidates: list[dict]) -> None:
    """Pretty-print an ambiguous brand match (id, website, name) to stderr."""
    err = Console(stderr=True)
    err.print(f"[yellow]{detail}[/yellow]")
    err.print()
    err.print(f"  {'brand_id':>10}  {'website':<30}  name")
    err.print(f"  {'-' * 10}  {'-' * 30}  {'-' * 40}")
    for c in candidates:
        website = (c.get("website") or "")[:30]
        err.print(f"  {c['id']:>10}  {website:<30}  {c['name']}")


SIMILAR_COLUMNS = ["score", "brand_id", "brand_name", "website", "mbn"]
SIMILAR_COLUMN_CONFIG = {
    "score": {"justify": "right"},
}


def _format_score(results: list[dict]) -> list[dict]:
    """Convert raw similarity score (0.0-1.0) to percentage string."""
    for row in results:
        score = row.get("score")
        if isinstance(score, (int, float)):
            row["score"] = f"{score * 100:.1f}%"
    return results


@app.command("similar")
def similar_cmd(
    query: str = typer.Argument(..., help="Brand name or numeric ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Find brands similar to a given one (by ID or name).

    Costs 25 credits per call. Intelligence plan required.

    Examples:
        tl brands similar Nike
        tl brands similar 6037
        tl brands similar 6037 mbn:yes --limit 10
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    encoded_query = urllib.parse.quote(query, safe="")
    params: dict[str, str] = {"limit": str(limit)}

    client = get_client()
    try:
        data = client.get(f"/brands/{encoded_query}/similar", params=params)
        brand_name = data.get("brand", {}).get("name", query)
        if fmt in ("table", "md"):
            _format_score(data.get("results", []))
        output(
            data,
            fmt,
            columns=SIMILAR_COLUMNS,
            title=f"Brands similar to {brand_name}",
            column_config=SIMILAR_COLUMN_CONFIG,
        )
    except ApiError as e:
        _handle_brand_api_error(e)
    finally:
        client.close()


WINNER_COLUMNS = [
    "sponsorships",
    "channel_id",
    "name",
    "msn",
    "tpp",
    "subscribers",
    "projected_views",
    "cpm",
    "sponsorship_score",
]
WINNER_COLUMN_CONFIG = {
    "sponsorships": {"justify": "right"},
    "subscribers": {"justify": "right"},
    "projected_views": {"justify": "right"},
    "cpm": {"justify": "right"},
    "sponsorship_score": {"justify": "right"},
}


@app.command("winner-channels")
def winner_channels_cmd(
    query: str = typer.Argument(..., help="Brand name, ID, slug, or domain"),
    args: list[str] = typer.Argument(None, help="Filters (key:value): tpp, msn, since, created-since"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max winner channels (1-200)"),
) -> None:
    """Channels a brand has repeatedly sponsored — the methodology's TRUE-renewal signal.

    Returns channels this brand sponsored at least 5 times within the lookback
    window (default 2 years), subscribers ≥ 10k, ranked by renewal count. These winners
    seed the look-alike expansion (`tl channels look-alike <id>`). Costs 5 credits
    per result. Intelligence plan required.

    Filters:
        tpp:<yes|no|both>       TL Partner Program (default: both)
        msn:<yes|no|both|DATE>  Media Selling Network; a YYYY-MM-DD lower-bounds the join date
        since:<date>            Count sponsorships on/after YYYY[-MM[-DD]] (default: 2 years ago)
        created-since:<date>    Only channels created on/after YYYY[-MM[-DD]]

    Examples:
        tl brands winner-channels Nike
        tl brands winner-channels 6037 msn:yes --limit 30
        tl brands winner-channels "Magic Spoon" since:2023-01-01
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    filters = parse_filters(args or [])
    params: dict[str, str] = {k: filters[k] for k in ("tpp", "msn", "since", "created-since") if k in filters}
    params["limit"] = str(limit)

    encoded_query = urllib.parse.quote(query, safe="")
    client = get_client()
    try:
        data = client.get(f"/brands/{encoded_query}/winner-channels", params=params)
        brand_name = data.get("brand", {}).get("name", query)
        for r in data.get("results", []):
            r["channel_id"] = r.pop("id", None)
        output(
            data,
            fmt,
            columns=WINNER_COLUMNS,
            title=f"Winner channels for {brand_name}",
            column_config=WINNER_COLUMN_CONFIG,
        )
    except ApiError as e:
        _handle_brand_api_error(e)
    finally:
        client.close()
