"""tl uploads — List video uploads."""

import typer

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.filters import parse_filters
from tl_cli.output.formatter import detect_format, output

app = typer.Typer(help="Video uploads (YouTube content from Elasticsearch)")


@app.callback(invoke_without_command=True)
def uploads(
    ctx: typer.Context,
    args: list[str] = typer.Argument(None, help="Filters (key:value pairs)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """List video uploads.

    Use 'tl upload <id>' to show details for a specific upload.

    Examples:
        tl uploads                                    # List recent uploads
        tl uploads channel:12345 type:longform        # Filter uploads
    """
    if ctx.invoked_subcommand is not None:
        return

    fmt = detect_format(json_output, csv_output, md_output, quiet)
    filters = parse_filters(args or [])

    client = get_client()
    try:
        params = {**filters, "limit": str(limit), "offset": str(offset)}
        data = client.get("/uploads", params=params)
        output(
            data,
            fmt,
            columns=["id", "title", "channel", "views", "publication_date", "content_type"],
            title="Uploads",
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
