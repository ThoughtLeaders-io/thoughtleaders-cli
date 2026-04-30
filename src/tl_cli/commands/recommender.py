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

app = typer.Typer(help="Vector recommender (tags, top-channels/profiles/brands, vector inspection, profile→channel similarity)")


TOP_CHANNEL_COLUMNS = ["value", "channel_id", "channel_name", "slug"]
TOP_PROFILE_COLUMNS = ["value", "profile_id", "profile_email", "brand_name", "brand_slug"]
TOP_BRAND_COLUMNS = ["value", "brand_slug", "brand_name", "profile_id"]
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
    query = _strip_quotes(" ".join(args or []).strip())
    params = {"q": query} if query else {}
    client = get_client()
    try:
        data = client.get("/recommender/tags", params=params)
        output(
            data,
            fmt,
            columns=["group", "field_name"],
            title="Recommender vector tags",
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def _strip_quotes(value: str) -> str:
    """Strip one matching pair of surrounding quotes if present.

    Lets users paste an example like `tl recommender top-channels "cooking"`
    where the shell already strips quotes, but also tolerates a layer of
    extra quoting from agents or scripts that re-wrap the literal.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _do_top(kind: str, tag: str, args: list[str], fmt: str, limit: int, columns: list[str], title: str) -> None:
    tag = _strip_quotes(tag)
    filters = parse_filters(args or [])
    server_keys = {"msn", "mbn", "exclude-for-channel", "exclude-for-profile"}
    params = {k: v for k, v in filters.items() if k in server_keys}
    params["tag"] = tag
    params["limit"] = str(limit)

    client = get_client()
    try:
        data = client.get(f"/recommender/top/{kind}", params=params)
        output(
            data,
            fmt,
            columns=columns,
            title=title,
            column_config=TOP_COLUMN_CONFIG,
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("top-channels")
def top_channels_cmd(
    tag: str = typer.Argument(..., help='Vector tag name (e.g. "Cooking", "Age 18-24"). Run `tl recommender tags` to discover valid names.'),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Top channels loaded on a single vector tag.

    Costs 50 credits per call. Intelligence plan required.

    Filters:
        msn:<yes|no|all>            MSN membership (default: all)
        exclude-for-profile:<id>    Drop channels already proposed for this profile

    Examples:
        tl recommender top-channels "Cooking"
        tl recommender top-channels "Tech" msn:yes --limit 30
        tl recommender top-channels "Cooking" exclude-for-profile:842
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    _do_top("channels", tag, args or [], fmt, limit, TOP_CHANNEL_COLUMNS, f"Top channels: {tag}")


@app.command("top-profiles")
def top_profiles_cmd(
    tag: str = typer.Argument(..., help='Vector tag name (e.g. "Cooking", "Age 18-24"). Run `tl recommender tags` to discover valid names.'),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Top brand profiles loaded on a single vector tag.

    Costs 50 credits per call. Intelligence plan required. Profiles can
    represent the same brand more than once (one brand → multiple
    profiles); use `top-brands` for brand-deduplicated results.

    Filters:
        mbn:<yes|no|all>            MBN membership (default: all)
        exclude-for-channel:<id>    Drop profiles already proposed for this channel

    Examples:
        tl recommender top-profiles "Cooking"
        tl recommender top-profiles "USA share" mbn:yes --limit 30
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    _do_top("profiles", tag, args or [], fmt, limit, TOP_PROFILE_COLUMNS, f"Top profiles: {tag}")


@app.command("top-brands")
def top_brands_cmd(
    tag: str = typer.Argument(..., help='Vector tag name (e.g. "Cooking", "Age 18-24"). Run `tl recommender tags` to discover valid names.'),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Top brands loaded on a single vector tag (deduplicated from profiles).

    Costs 50 credits per call. Intelligence plan required. Server-side
    aggregates the underlying profile rows by brand, keeping the
    highest-scoring profile per brand.

    Filters:
        mbn:<yes|no|all>            MBN membership of the underlying profile (default: all)
        exclude-for-channel:<id>    Drop brands already proposed for this channel

    Examples:
        tl recommender top-brands "Cooking"
        tl recommender top-brands "USA share" mbn:yes --limit 30
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    _do_top("brands", tag, args or [], fmt, limit, TOP_BRAND_COLUMNS, f"Top brands: {tag}")


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
