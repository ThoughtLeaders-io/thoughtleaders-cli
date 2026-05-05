"""Shared helpers for entity comment subcommands.

Each entity (sponsorships, channels, brands, uploads) exposes
`comment-add`, `comment-list`, and `comment-edit` subcommands that
delegate to these helpers. Comments are free (no credits charged).

The server-side endpoints are:
    GET/POST /<entity_type>/<entity_id>/comments
    PATCH    /comment/<comment_id>
"""

import typer

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output, output_single

COLUMNS = ["comment_id", "author", "text", "created_at"]


def list_comments(entity_type: str, entity_id: str, json_output: bool, toon_output: bool) -> None:
    fmt = detect_format(json_output, False, False, toon_output)
    client = get_client()
    try:
        data = client.get(f"/{entity_type}/{entity_id}/comments")
        for r in data.get("results", []):
            r["comment_id"] = r.pop("id", None)
        output(
            data,
            fmt,
            columns=COLUMNS,
            title=f"Comments on {entity_type} {entity_id}",
        )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def add_comment(entity_type: str, entity_id: str, message: str, json_output: bool, toon_output: bool) -> None:
    fmt = detect_format(json_output, False, False, toon_output)
    client = get_client()
    try:
        data = client.post(f"/{entity_type}/{entity_id}/comments", json_body={"text": message})
        for r in data.get("results", []):
            r["comment_id"] = r.pop("id", None)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def edit_comment(comment_id: int, message: str, json_output: bool, toon_output: bool) -> None:
    fmt = detect_format(json_output, False, False, toon_output)
    client = get_client()
    try:
        data = client.patch(f"/comment/{comment_id}", json_body={"text": message})
        for r in data.get("results", []):
            r["comment_id"] = r.pop("id", None)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def register_comment_commands(app: typer.Typer, entity_type: str, entity_label: str) -> None:
    """Register comment-list / comment-add / comment-edit subcommands on `app`.

    `entity_type` matches the server URL segment (sponsorship / channel /
    brand / upload). `entity_label` is the user-facing word shown in help
    text (e.g. "sponsorship", "channel").
    """

    @app.command("comment-list")
    def comment_list(
        entity_id: str = typer.Argument(..., help=f"{entity_label.capitalize()} ID"),
        json_output: bool = typer.Option(False, "--json", help="JSON output"),
        toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    ) -> None:
        f"""List comments on a {entity_label} (free, no credits)."""
        list_comments(entity_type, entity_id, json_output, toon_output)

    @app.command("comment-add")
    def comment_add(
        entity_id: str = typer.Argument(..., help=f"{entity_label.capitalize()} ID"),
        message: str = typer.Argument(..., help="Comment text"),
        json_output: bool = typer.Option(False, "--json", help="JSON output"),
        toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    ) -> None:
        f"""Add a comment to a {entity_label} (free, no credits)."""
        add_comment(entity_type, entity_id, message, json_output, toon_output)

    @app.command("comment-edit")
    def comment_edit(
        comment_id: int = typer.Argument(..., help="Comment ID"),
        message: str = typer.Argument(..., help="New comment text"),
        json_output: bool = typer.Option(False, "--json", help="JSON output"),
        toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
    ) -> None:
        """Edit an existing comment (free, no credits).

        Only the comment's author can edit it (superusers can edit any comment).
        """
        edit_comment(comment_id, message, json_output, toon_output)
