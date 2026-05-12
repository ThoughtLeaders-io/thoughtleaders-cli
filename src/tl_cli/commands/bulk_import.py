"""tl bulk-import - bulk-add or exclude entities from a report.

Superuser-only on the server side. Submits a list of identifiers
(channels / brands / articles / sponsorships) against a target report
and polls until the import completes.
"""

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client

err = Console(stderr=True)

POLL_INTERVAL_SEC = 2
POLL_TIMEOUT_SEC = 600
VALID_ENTITIES = ("channels", "brands", "articles", "sponsorships")


def _read_ids(ids_file: str | None) -> list[str]:
    if ids_file:
        text = Path(ids_file).read_text()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        err.print("[red]Provide --ids-file or pipe identifiers via stdin.[/red]")
        raise typer.Exit(2)
    ids = [line.strip() for line in text.splitlines() if line.strip()]
    if not ids:
        err.print("[red]No identifiers found.[/red]")
        raise typer.Exit(2)
    return ids


def _poll_until_done(client, task_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT_SEC
    with err.status(f"[bold blue]Importing... (task {task_id})[/bold blue]"):
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL_SEC)
            data = client.get(f"/bulk-import/poll/{task_id}")
            if data.get("finished"):
                if data.get("error"):
                    err.print(f"[red]Import failed: {data.get('error')}[/red]")
                    raise typer.Exit(1)
                return data.get("end_result") or {}
    err.print(f"[red]Polling timed out after {POLL_TIMEOUT_SEC}s. Task still running: {task_id}[/red]")
    raise typer.Exit(3)


def bulk_import_command(
    entity: str = typer.Argument(..., help=f"Entity type: one of {', '.join(VALID_ENTITIES)}"),
    campaign: int = typer.Option(..., "--campaign", "-c", help="Target report ID"),
    ids_file: str | None = typer.Option(None, "--ids-file", "-f", help="Path to file with one identifier per line. Omit to read from stdin."),
    exclude: bool = typer.Option(False, "--exclude", help="Mark these identifiers as excluded from the report instead of included"),
    json_output: bool = typer.Option(False, "--json", help="JSON output (default)"),
) -> None:
    """Bulk-import entities into a report.

    Accepts a list of identifiers per entity:
      channels      -> numeric IDs, YouTube channel IDs (UC...), @handles, full URLs
      brands        -> numeric IDs, slugs, websites/domains
      articles      -> video IDs or URLs
      sponsorships  -> AdLink IDs (numeric)

    Submits the list and polls until the import completes. Channels/brands
    that aren't already on file get auto-created from YouTube / their
    website. Enrichment (metadata, AI description, demographics) is queued
    and lands a few minutes after the import returns.

    Examples:
        tl bulk-import channels --campaign 23859 --ids-file ./channels.txt
        echo "@mkbhd" | tl bulk-import channels -c 23859
        tl bulk-import brands -c 23859 -f ./brands.txt --exclude

    Requires superuser permission - non-superusers get a 403.
    """
    if entity not in VALID_ENTITIES:
        err.print(f"[red]entity must be one of: {', '.join(VALID_ENTITIES)}[/red]")
        raise typer.Exit(2)

    ids = _read_ids(ids_file)

    body = {
        "campaign_id": campaign,
        "entity": entity,
        "entity_ids": ids,
        "include": not exclude,
    }

    err.print(f"[dim]Submitting {len(ids)} {entity} to report {campaign} (include={not exclude})...[/dim]")

    client = get_client()
    try:
        submit = client.post("/bulk-import", json_body=body)
    except ApiError as e:
        handle_api_error(e)
        raise typer.Exit(1)

    task_id = submit.get("task_id")
    if not task_id:
        err.print(f"[red]No task_id in submit response: {submit}[/red]")
        raise typer.Exit(1)

    try:
        result = _poll_until_done(client, task_id)
    finally:
        client.close()

    output = {"task_id": task_id, **result}
    if json_output or not sys.stdout.isatty():
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        Console().print_json(json.dumps(output))
