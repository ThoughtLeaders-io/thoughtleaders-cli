"""tl uploads — Show video uploads by ID."""

import typer

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.commands._comments_common import register_comment_commands
from tl_cli.output.formatter import detect_format, output_single

app = typer.Typer(help="Video uploads (YouTube content from Elasticsearch)")
register_comment_commands(app, "upload", "upload")


@app.command("show")
def show_cmd(
    ids: list[str] = typer.Argument(..., help="One or more upload IDs"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show details for one or more uploads by ID.

    IDs can contain colons (e.g. 1174310:0BehkmVa7ak).

    Examples:
        tl uploads show 0BehkmVa7ak
        tl uploads show 1174310:0BehkmVa7ak
        tl uploads show 0BehkmVa7ak dQw4w9WgXcQ
    """
    fmt = detect_format(json_output, False, False, toon_output)

    client = get_client()
    try:
        for upload_id in ids:
            data = client.get(f"/uploads/{upload_id}")
            for r in (data.get("results", []) if isinstance(data.get("results"), list) else []):
                r["upload_id"] = r.pop("id", None)
            output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
