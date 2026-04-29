"""tl recommender — Vector-recommender introspection and discovery.

Surfaces the channel/profile feature-vector machinery that powers the
"Recommender Insights" web view: list the vector tags (categories,
demographics, formats, etc.), find the top channels and profiles loaded
on a given tag, inspect a single channel or brand vector, or fetch
channels similar to a brand profile's ideal vector.

For 1:1 similarity use `tl channels similar` and `tl brands similar`.
"""

import urllib.parse

import typer
from rich.console import Console

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.filters import parse_filters
from tl_cli.output.formatter import detect_format, output, output_single

app = typer.Typer(help="Vector recommender (tags, top-by-tag, vector inspection, profile→channel similarity)")


TOP_COLUMNS = ["kind", "value", "channel_id", "profile_id", "name", "brand_name", "slug"]
TOP_COLUMN_CONFIG = {"value": {"justify": "right"}}


def _handle_recommender_error(e: ApiError) -> None:
    """Show ambiguity candidates inline; otherwise default handler."""
    if e.status_code == 400 and isinstance(e.raw, dict) and e.raw.get("candidates"):
        err = Console(stderr=True)
        err.print(f"[yellow]{e.detail}[/yellow]")
        err.print()
        err.print("[bold]Candidates:[/bold]")
        for c in e.raw["candidates"]:
            cid = c.get("channel_id") or c.get("brand_id") or "?"
            name = c.get("name", "")
            extra = c.get("website") or c.get("subscribers") or ""
            err.print(f"  {cid:>10}  {name}  [dim]{extra}[/dim]")
        raise typer.Exit(1)
    handle_api_error(e)


@app.callback(invoke_without_command=True)
def recommender(ctx: typer.Context) -> None:
    """Vector recommender."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("tags")
def tags_cmd(
    args: list[str] = typer.Argument(None, help="Optional substring (matches tag or normalized name)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """List vector tag names (free).

    Use this to discover the tag names accepted by `tl recommender top`.
    Each tag is one dimension of a channel/profile feature vector —
    e.g. content categories like "Cooking", demographic buckets like
    "Age 18-24", device shares, country shares.

    Examples:
        tl recommender tags
        tl recommender tags cooking
        tl recommender tags "age 18"
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    query = " ".join(args or []).strip()
    params = {"q": query} if query else {}
    client = get_client()
    try:
        data = client.get("/recommender/tags", params=params)
        output(
            data,
            fmt,
            columns=["group", "field_name", "normalized_name"],
            title="Recommender vector tags",
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("top")
def top_cmd(
    tag: str = typer.Argument(..., help='Vector tag name (e.g. "Cooking", "Age 18-24"). Run `tl recommender tags` to discover valid names.'),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results per group (1-100)"),
) -> None:
    """Top channels and profiles loaded on a single vector tag.

    Costs 50 credits per call. Intelligence plan required. Returns both
    channels and profiles ranked by the tag's value (descending).

    Filters:
        msn:<yes|no|all>            MSN membership for channel rows (default: all)
        mbn:<yes|no|all>            MBN membership for profile rows (default: all)
        exclude-for-channel:<id>    Drop profiles already proposed for this channel
        exclude-for-profile:<id>    Drop channels already proposed for this profile

    Examples:
        tl recommender top "Cooking"
        tl recommender top "Tech" msn:yes --limit 30
        tl recommender top "USA share" mbn:yes
        tl recommender top "Cooking" exclude-for-profile:842
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    filters = parse_filters(args or [])

    server_keys = {"msn", "mbn", "exclude-for-channel", "exclude-for-profile"}
    params = {k: v for k, v in filters.items() if k in server_keys}
    params["tag"] = tag
    params["limit"] = str(limit)

    client = get_client()
    try:
        data = client.get("/recommender/top", params=params)
        rows = data.get("results", [])
        for r in rows:
            r["name"] = r.get("channel_name") or r.get("profile_email") or ""
        output(
            data,
            fmt,
            columns=TOP_COLUMNS,
            title=f"Top by tag: {tag}",
            column_config=TOP_COLUMN_CONFIG,
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("inspect-channel")
def inspect_channel_cmd(
    channel_ref: str = typer.Argument(..., help="Channel ID (numeric) or name (partial match, must be unique)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show a channel's feature vector grouped by category.

    Costs 50 credits per call. Intelligence plan required. Returns the
    grouped sparse vector (active dimensions only) and the magnitude.

    Examples:
        tl recommender inspect-channel 12345
        tl recommender inspect-channel "MrBeast"
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    encoded = urllib.parse.quote(channel_ref, safe="")
    client = get_client()
    try:
        data = client.get(f"/recommender/channels/{encoded}/inspect")
        output_single(data, fmt)
    except ApiError as e:
        _handle_recommender_error(e)
    finally:
        client.close()


@app.command("inspect-brand")
def inspect_brand_cmd(
    brand_ref: str = typer.Argument(..., help="Brand ID (numeric) or name (partial match, must be unique)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show a brand profile's ideal feature vector grouped by category.

    Costs 50 credits per call. Intelligence plan required. Resolves the
    brand to its (preferred MBN) profile and inspects that profile's
    aggregated vector.

    Examples:
        tl recommender inspect-brand 287
        tl recommender inspect-brand Nike
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    encoded = urllib.parse.quote(brand_ref, safe="")
    client = get_client()
    try:
        data = client.get(f"/recommender/brands/{encoded}/inspect")
        output_single(data, fmt)
    except ApiError as e:
        _handle_recommender_error(e)
    finally:
        client.close()


@app.command("similar-to-profile")
def similar_to_profile_cmd(
    profile_id: int = typer.Argument(..., help="Profile ID (numeric)"),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Channels closest to a brand profile's ideal vector.

    Costs 50 credits per call. Intelligence plan required. Channels the
    brand has already worked with or been proposed are excluded.

    Filters:
        language:<iso>      Content language (default: en)
        msn:<yes|no>        Restrict to MSN channels (default: no)

    Examples:
        tl recommender similar-to-profile 842
        tl recommender similar-to-profile 842 msn:yes --limit 30
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    filters = parse_filters(args or [])
    params = {k: v for k, v in filters.items() if k in {"language", "msn"}}
    params["limit"] = str(limit)
    client = get_client()
    try:
        data = client.get(f"/recommender/profiles/{profile_id}/similar", params=params)
        for r in data.get("results", []):
            score = r.get("score")
            if isinstance(score, (int, float)) and fmt in ("table", "md"):
                r["score"] = f"{score * 100:.1f}%"
        output(
            data,
            fmt,
            columns=["score", "channel_id", "channel_name", "slug"],
            title=f"Channels similar to profile {profile_id}",
            column_config={"score": {"justify": "right"}},
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
