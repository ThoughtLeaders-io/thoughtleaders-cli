"""tl channels — Search and show YouTube channels."""

import json as _json
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

app = typer.Typer(cls=AlphaSortedTyperGroup, help="YouTube channels (detail and similar-channel recommendations)")
register_comment_commands(app, "channel", "channel")

_HISTORY_DEPRECATION = (
    "[deprecation] `tl channels history` is deprecated and will be removed. "
    "Use `tl db es` filtered by `channel.id: <id>` on docs with non-empty "
    "`sponsored_brand_mentions`, joined to `thoughtleaders_brand` via "
    "`tl db pg` for brand names."
)


def _warn_deprecated(message: str) -> None:
    Console(stderr=True).print(f"[yellow]{message}[/yellow]")


# Columns for the `similar` endpoint result table. The server enriches every
# row so the user can size up each suggestion without follow-up queries.
SIMILAR_COLUMNS = ["score", "channel_id", "name", "msn", "tpp", "subscribers", "projected_views", "total_views", "cpm", "audience"]
SIMILAR_COLUMN_CONFIG = {
    "score": {"justify": "right"},
    "subscribers": {"justify": "right"},
    "projected_views": {"justify": "right"},
    "total_views": {"justify": "right"},
    "cpm": {"justify": "right"},
}

# Columns for the `look-alike` endpoint. Unlike `similar`, the score is the
# methodology's 0–100 composite (already weighted), and each row carries the
# scoring inputs (sponsorship_score) the matcher uses downstream.
LOOKALIKE_COLUMNS = [
    "score",
    "channel_id",
    "name",
    "msn",
    "tpp",
    "subscribers",
    "projected_views",
    "cpm",
    "sponsorship_score",
    "audience",
]
LOOKALIKE_COLUMN_CONFIG = {
    "score": {"justify": "right"},
    "subscribers": {"justify": "right"},
    "projected_views": {"justify": "right"},
    "cpm": {"justify": "right"},
    "sponsorship_score": {"justify": "right"},
}


@app.command("show")
def show_cmd(
    channel_ref: str = typer.Argument(..., help="Channel ID (numeric) or name (partial match, must be unique)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output (flattens adspots: one row per adspot)"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show channel detail by ID or name (includes active adspots).

    Accepts either a numeric channel ID or a partial name. Names that
    match more than one active channel return a 400 with the candidate
    IDs listed so you can retry with a specific ID.

    Examples:
        tl channels show 12345
        tl channels show "Economics Explained"
        tl channels show 12345 --csv > channel.csv
    """
    fmt = detect_format(json_output, csv_output, False, toon_output)

    encoded_ref = urllib.parse.quote(channel_ref, safe="")
    client = get_client()
    try:
        data = client.get(f"/channels/{encoded_ref}")
        output_single(data, fmt)
        if fmt == "table" and data.get("show_cta"):
            record = data.get("results", data)
            if isinstance(record, list) and record:
                record = record[0]
            if isinstance(record, dict):
                hint = detail_hint(client, channel=record.get("name"))
                if hint:
                    Console(stderr=True).print(f"\n[yellow]{hint}[/yellow]")
    except ApiError as e:
        _handle_channel_api_error(e)
    finally:
        client.close()


def _print_channel_candidates(detail: str, candidates: list[dict]) -> None:
    """Pretty-print an ambiguous-match list (id, subscribers, name) to stderr."""
    err = Console(stderr=True)
    err.print(f"[yellow]{detail}[/yellow]")
    err.print()
    err.print(f"  {'channel_id':>10}  {'subscribers':>12}  name")
    err.print(f"  {'-' * 10}  {'-' * 12}  {'-' * 40}")
    for c in candidates:
        subs = c.get("subscribers") or 0
        try:
            subs_str = f"{int(subs):>12,}"
        except (TypeError, ValueError):
            subs_str = f"{'?':>12}"
        err.print(f"  {c['id']:>10}  {subs_str}  {c['name']}")


def _handle_channel_api_error(e: ApiError) -> None:
    """Print a candidates list for 400 responses with `candidates` in the
    body (ambiguous channel name) and exit 1; otherwise defer to the
    default handler. Used by both `show` and `similar` since they share
    the server-side _resolve_channel helper and the same error shape.
    """
    if e.status_code == 400 and isinstance(e.raw, dict) and e.raw.get("candidates"):
        err = Console(stderr=True)
        err.print(f"[yellow]{e.detail}[/yellow]")
        err.print()
        err.print("[bold]Candidates:[/bold]")
        err.print(f"  {'channel_id':>10}  {'subscribers':>12}  name")
        err.print(f"  {'-' * 10}  {'-' * 12}  {'-' * 40}")
        for c in e.raw["candidates"]:
            subs = c.get("subscribers") or 0
            err.print(f"  {c['channel_id']:>10}  {subs:>12,}  {c['name']}")
        raise typer.Exit(1)
    handle_api_error(e)


def _format_score(results: list[dict]) -> list[dict]:
    """Convert raw similarity score (0.0-1.0) to percentage string for table/csv/md."""
    for row in results:
        score = row.get("score")
        if isinstance(score, (int, float)):
            row["score"] = f"{score * 100:.1f}%"
    return results


def _apply_client_side_filters(results: list[dict], filters: dict) -> list[dict]:
    """Category / subscriber-band / exclude post-filters shared by `similar`
    and `look-alike` (both enrich rows the same way before this runs)."""
    if "category" in filters:
        target = filters["category"]
        results = [r for r in results if str(r.get("category", "")) == target]
    if "min-subs" in filters:
        try:
            n = int(filters["min-subs"])
            results = [r for r in results if (r.get("subscribers") or 0) >= n]
        except ValueError:
            pass
    if "max-subs" in filters:
        try:
            n = int(filters["max-subs"])
            results = [r for r in results if (r.get("subscribers") or 0) <= n]
        except ValueError:
            pass
    if "exclude" in filters:
        excluded = {int(x) for x in filters["exclude"].split(",") if x.strip().isdigit()}
        results = [r for r in results if r.get("id") not in excluded]
    return results


def _do_similar(channel_ref: str, args: list[str], fmt: str, limit: int) -> None:
    """Implementation for `similar` — the generic feature-vector KNN.

    Server-side filters: language, msn, min-score (passed through in the
    query string). Client-side filters: category, min-subs, max-subs,
    exclude (applied to the returned, enriched rows).
    """
    filters = parse_filters(args)

    # Split filters into server-side and client-side sets.
    server_keys = {"language", "msn", "min-score"}
    server_params = {k: filters.pop(k) for k in list(filters) if k in server_keys}
    server_params["limit"] = str(limit)

    encoded_ref = urllib.parse.quote(channel_ref, safe="")
    client = get_client()
    try:
        data = client.get(f"/channels/{encoded_ref}/similar", params=server_params)

        data["results"] = _apply_client_side_filters(data.get("results", []), filters)
        for r in data["results"]:
            r["channel_id"] = r.pop("id", None)
        if fmt in ("table", "md"):
            _format_score(data["results"])
        output(
            data,
            fmt,
            columns=SIMILAR_COLUMNS,
            title=f"Channels similar to {channel_ref}",
            column_config=SIMILAR_COLUMN_CONFIG,
        )
    except ApiError as e:
        _handle_channel_api_error(e)
    finally:
        client.close()


def _do_lookalike(channel_ref: str, args: list[str], fmt: str, limit: int) -> None:
    """Implementation for `look-alike` — the methodology's audience/topic look-alike.

    Hits /channels/<ref>/lookalike (audience + topic embeddings, 15-factor
    re-weighting) — distinct from `similar` (the generic feature-vector KNN).
    Server-side filters: msn, tpp, created-since. Client-side: category,
    min-subs, max-subs, exclude. The score is the 0–100 composite the endpoint
    already computed, so it is shown as-is (not rescaled like `similar`).
    """
    filters = parse_filters(args)
    server_keys = {"msn", "tpp", "created-since"}
    server_params = {k: filters.pop(k) for k in list(filters) if k in server_keys}
    server_params["limit"] = str(limit)

    encoded_ref = urllib.parse.quote(channel_ref, safe="")
    client = get_client()
    try:
        data = client.get(f"/channels/{encoded_ref}/lookalike", params=server_params)
        data["results"] = _apply_client_side_filters(data.get("results", []), filters)
        for r in data["results"]:
            r["channel_id"] = r.pop("id", None)
        output(
            data,
            fmt,
            columns=LOOKALIKE_COLUMNS,
            title=f"Look-alike channels for {channel_ref}",
            column_config=LOOKALIKE_COLUMN_CONFIG,
        )
    except ApiError as e:
        _handle_channel_api_error(e)
    finally:
        client.close()


@app.command("similar")
def similar_cmd(
    channel_ref: str = typer.Argument(..., help="Channel ID (numeric) or name (partial match, must be unique)"),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs). Run 'tl describe show channels' for available filters."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Find channels similar to a given one (by id or name).

    Costs 25 credits per call. Intelligence plan required. Results are
    ranked by similarity and enriched with subscribers, projected_views,
    total_views, category, and the channel's representative CPM.

    Server-side filters (pushed to the recommender):
        language:<iso>      Restrict to a content language (default: en)
        msn:<true|false>    Restrict to Media Selling Network (default: true)
        min-score:<0-1>     Minimum similarity (default: 0.5)

    Client-side post-filters (applied after fetch):
        category:<code>     Keep only rows matching this content_category
        min-subs:<N>        Subscribers >= N
        max-subs:<N>        Subscribers <= N
        exclude:<id,id,…>   Drop specific channel ids

    Examples:
        tl channels similar 12345
        tl channels similar "MrBeast" language:en msn:false
        tl channels similar 12345 min-score:0.7 min-subs:1000000 --limit 10
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    _do_similar(channel_ref, args or [], fmt, limit)


@app.command("history", deprecated=True)
def history_cmd(
    channel_ref: str = typer.Argument(..., help="Channel ID (numeric) or name (partial match, must be unique)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """Deprecated. Show a channel's sponsorship history (videos with detected sponsors).

    Prefer `tl db es` with `channel.id: <id>` + non-empty
    `sponsored_brand_mentions`, joined to `thoughtleaders_brand` via
    `tl db pg` for brand names. Requires an Intelligence plan.
    """
    _warn_deprecated(_HISTORY_DEPRECATION)
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    encoded_ref = urllib.parse.quote(channel_ref, safe="")
    client = get_client()
    try:
        params = {"limit": str(limit), "offset": str(offset)}
        data = client.get(f"/channels/{encoded_ref}/history", params=params)
        channel_name = data.get("channel", {}).get("name", channel_ref)
        output(
            data,
            fmt,
            columns=["video_id", "title", "brands", "views", "publication_date", "is_tl"],
            title=f"Channel History: {channel_name}",
        )
    except ApiError as e:
        _handle_channel_api_error(e)
    finally:
        client.close()


@app.command("update")
def update_cmd(
    channel_id: int = typer.Argument(..., help="Channel ID (numeric)"),
    fields: str = typer.Argument(..., help="JSON object of fields to update"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Update a channel.

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
        data = client.post(f"/channels/{channel_id}/edit", json_body=body)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("find")
def find_cmd(
    query: str = typer.Argument(..., help="Name, slug, YouTube URL, handle, channel ID, or video URL"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Resolve a string to a single channel.

    Accepts:
      - A partial channel name or slug (substring match, falling back to
        fuzzy similarity — spacing/typo variants like "Deco Destiny" still
        resolve a channel named "DecoDestiny")
      - A YouTube channel URL (https://youtube.com/channel/UC...,
        https://youtube.com/@handle, /c/<name>, /user/<name>)
      - A raw YouTube channel ID (UC...) or @handle
      - A YouTube video URL — the video's channel is resolved via the
        platform's article index

    Default output is a pretty `id  name` line on stdout. Pass --json /
    --csv / --md / --toon for machine-readable output (the JSON shape is
    `{"id": ..., "name": ...}`).

    Ambiguous matches return an error with candidate IDs and names.
    If the input is a YouTube URL — or a name that YouTube resolves to
    a channel not yet in the index — it is queued for analysis; check
    back in about 24 hours.

    Examples:
        tl channels find "MrBeast"
        tl channels find https://www.youtube.com/@MrBeast
        tl channels find https://www.youtube.com/watch?v=dQw4w9WgXcQ
        tl channels find UCX6OQ3DkcsbYNE6H8uQQuVA
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    client = get_client()
    try:
        data = client.get("/channels/find", params={"q": query})
        results = data.get("results", [])
        record = results[0] if results else {}
        if fmt == "table":
            cid = record.get("id")
            name = record.get("name")
            if cid is None:
                Console(stderr=True).print("[yellow]No match.[/yellow]")
                raise typer.Exit(1)
            Console().print(f"[bold cyan]{cid}[/bold cyan]  {name}")
        else:
            output(
                {"results": [{"id": record.get("id"), "name": record.get("name")}]},
                fmt,
                columns=["id", "name"],
                title=f"Channel match for {query}",
            )
    except ApiError as e:
        if e.status_code == 400 and isinstance(e.raw, dict) and e.raw.get("candidates"):
            if fmt == "table":
                _print_channel_candidates(e.detail, e.raw["candidates"])
            else:
                # Machine-readable output: emit candidates through the
                # standard formatter so --json / --csv / --md / --toon all
                # produce the same structural surface the success path uses.
                Console(stderr=True).print(f"[yellow]{e.detail}[/yellow]")
                output(
                    {"detail": e.detail, "results": e.raw["candidates"]},
                    fmt,
                    columns=["id", "name", "subscribers"],
                    title="Ambiguous match — candidates",
                )
            raise typer.Exit(1)
        if e.status_code == 404 and isinstance(e.raw, dict) and e.raw.get("queued"):
            if fmt == "table":
                err = Console(stderr=True)
                err.print(f"[yellow]{e.detail}[/yellow]")
                err.print(f"  [dim]queued_channel_id={e.raw.get('queued_channel_id')}  queued_url={e.raw.get('queued_url')}[/dim]")
            else:
                Console(stderr=True).print(f"[yellow]{e.detail}[/yellow]")
                output_single(
                    {
                        "detail": e.detail,
                        "queued": True,
                        "queued_channel_id": e.raw.get("queued_channel_id"),
                        "queued_url": e.raw.get("queued_url"),
                    },
                    fmt,
                )
            raise typer.Exit(1)
        handle_api_error(e)
    finally:
        client.close()


@app.command("look-alike")
def look_alike_cmd(
    channel_ref: str = typer.Argument(..., help="Channel ID (numeric) or name (partial match, must be unique)"),
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs). Run 'tl describe show channels' for available filters."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results (1-100)"),
) -> None:
    """Find a channel's look-alike audience channels — the matching methodology's signal.

    Searches the channel's audience embedding (MSN channels) and topic-description
    embedding, then re-weights candidates by ~15 similarity factors (keyword overlap,
    demographics, posting cadence, video duration, …). This is the exact primitive the
    brand→channel matcher uses for its look-alike tiers — distinct from
    `tl channels similar` (the generic feature-vector KNN). Costs 25 credits per
    result. Intelligence plan required.

    Server-side filters:
        msn:<yes|no|both>       Restrict to Media Selling Network (default: both)
        tpp:<yes|no|both>       Restrict to TL Partner Program (default: both)
        created-since:<date>    Only channels created on/after YYYY[-MM[-DD]]

    Client-side post-filters (applied after fetch):
        category:<code>     Keep only rows matching this content_category
        min-subs:<N>        Subscribers >= N
        max-subs:<N>        Subscribers <= N
        exclude:<id,id,…>   Drop specific channel ids

    Examples:
        tl channels look-alike 12345
        tl channels look-alike "MrBeast" msn:yes --limit 30
    """
    fmt = detect_format(json_output, csv_output, md_output, toon_output)
    _do_lookalike(channel_ref, args or [], fmt, limit)
