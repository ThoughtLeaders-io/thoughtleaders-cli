"""tl upload — Show details for one or more uploads by ID."""

import typer

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output_single

app = typer.Typer(help="Upload detail — show one or more uploads by ID")


@app.callback(invoke_without_command=True)
def upload(
    ctx: typer.Context,
    ids: list[str] = typer.Argument(..., help="One or more upload IDs"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
) -> None:
    """Show details for one or more uploads by ID.

    IDs can contain colons (e.g. 1174310:0BehkmVa7ak).

    Examples:
        tl upload 0BehkmVa7ak
        tl upload 1174310:0BehkmVa7ak
        tl upload 0BehkmVa7ak dQw4w9WgXcQ    # Multiple uploads
    """
    if ctx.invoked_subcommand is not None:
        return

    fmt = detect_format(json_output, False, False, quiet)

    client = get_client()
    try:
        for upload_id in ids:
            data = client.get(f"/uploads/{upload_id}")
            output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
