"""tl brands — Brand intelligence reports."""

import urllib.parse

import typer

from rich.console import Console

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.hints import detail_hint
from tl_cli.output.formatter import detect_format, output

app = typer.Typer(help="Brand intelligence (sponsorship activity, channel mentions)")


@app.command("show")
def show_cmd(
    query: str = typer.Argument(..., help="Brand name or numeric ID"),
    channel: int | None = typer.Option(None, "--channel", "-c", help="Filter to a specific channel"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """Research a brand's sponsorship activity and channel mentions.

    Requires an Intelligence plan.

    Examples:
        tl brands show Nike                          # Nike's sponsorship intelligence
        tl brands show 21416                         # By brand ID
        tl brands show Nike --channel 12345          # Nike mentions on a specific channel
    """
    fmt = detect_format(json_output, csv_output, md_output, quiet)

    params: dict[str, str] = {"limit": str(limit), "offset": str(offset)}
    if channel is not None:
        params["channel_id"] = str(channel)

    encoded_query = urllib.parse.quote(query, safe="")
    client = get_client()
    try:
        data = client.get(f"/brands/{encoded_query}", params=params)
        brand_name = data.get("brand", {}).get("name", query)
        output(
            data,
            fmt,
            columns=["channel", "mentions", "type", "latest_date", "views"],
            title=f"Brand Intelligence: {brand_name}",
        )
        if fmt == "table" and data.get("results"):
            hint = detail_hint(client, brand=brand_name)
            if hint:
                Console(stderr=True).print(f"\n[yellow]{hint}[/yellow]")
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
