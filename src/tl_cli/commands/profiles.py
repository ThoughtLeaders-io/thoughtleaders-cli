"""tl profiles — Brand/publisher profile operations."""

import json as _json

import typer
from rich.console import Console

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output_single

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Brand/publisher profiles (update; full-access only)")


@app.callback()
def _profiles() -> None:
    """Brand/publisher profiles.

    The callback keeps `update` an explicit subcommand — without it Typer
    collapses a single-command group into the group itself.
    """


@app.command("update")
def update_cmd(
    profile_id: int = typer.Argument(..., help="Profile ID (numeric)"),
    fields: str = typer.Argument(..., help="JSON object of fields to update"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Update a profile. Full-access only.

    Editable fields: superuser_notes (free-text, max 2500 chars; send null
    to clear). Unknown fields are rejected with a 400 listing the
    offending key.

    Examples:
        tl profiles update 8871 '{"superuser_notes": "VIP account — always cc the AM lead"}'
        tl profiles update 8871 '{"superuser_notes": null}'
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
        data = client.post(f"/profiles/{profile_id}/edit", json_body=body)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
