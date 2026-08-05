"""tl memory — read and update your profile memory.

Your profile memory is the free-text summary of who you are and what you want from
sponsorships. The onboarding interview writes it first; these commands are how it
stays current afterwards.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape as rich_escape

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output_single

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Your profile memory (show; add a fact; replace)")

# `add` folds the fact into the existing memory with a model call whose duration
# scales with how much memory there is to rewrite, so it can run far past the
# client's 30s default. `set` is a plain replace and needs no extra room.
_ADD_TIMEOUT_SECONDS = 180.0


@app.command("show")
def show_cmd(
    profile_id: int | None = typer.Option(None, "--profile-id", help="Another profile's memory (full-access only)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show your profile memory and the preferences derived from it.

    Examples:
        tl memory show
        tl memory show --json
        tl memory show --profile-id 8871
    """
    fmt = detect_format(json_output, False, False, toon_output)
    params = {"profile_id": profile_id} if profile_id is not None else {}

    client = get_client()
    try:
        data = client.get("/memory", params=params)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("add")
def add_cmd(
    fact: str = typer.Argument(..., help="One new fact about you"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Fold one new fact into your profile memory.

    The fact is merged into what's already there — everything still true is kept,
    and only what the new fact contradicts is replaced. Always writes to your own
    profile.

    Examples:
        tl memory add "We stopped doing finance sponsorships."
        tl memory add "Now targeting 18-24 in the US."
    """
    fmt = detect_format(json_output, False, False, toon_output)
    if not fact.strip():
        Console(stderr=True).print("[red]Error:[/red] fact cannot be empty.")
        raise typer.Exit(1)

    client = get_client()
    try:
        data = client.post("/memory", json_body={"fact": fact.strip()}, timeout=_ADD_TIMEOUT_SECONDS)
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("set")
def set_cmd(
    memory: str = typer.Argument(None, help="The full replacement text"),
    from_file: Path | None = typer.Option(None, "--from-file", help="Read the replacement text from a file"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Replace your profile memory wholesale.

    The repair hatch for when a merge has gone wrong — unlike `add`, this is not
    length-guarded, so it will happily replace a long blob with a short one.
    Prefer `add` for ordinary updates.

    Examples:
        tl memory set "Runs a finance channel. Avoids crypto."
        tl memory set --from-file ./memory.txt
    """
    fmt = detect_format(json_output, False, False, toon_output)
    err = Console(stderr=True)

    if memory is not None and from_file is not None:
        err.print("[red]Error:[/red] pass either the replacement text or --from-file, not both.")
        raise typer.Exit(1)
    if memory is None and from_file is None:
        err.print("[red]Error:[/red] pass the replacement text, or --from-file to read it from a file.")
        raise typer.Exit(1)

    if from_file is not None:
        try:
            memory = from_file.read_text(encoding="utf-8")
        # A non-text file raises UnicodeDecodeError, a ValueError rather than an
        # OSError. The path and the error text are escaped because a bracket in
        # either would abort on a markup error and lose the message itself.
        except (OSError, UnicodeDecodeError) as exc:
            err.print(f"[red]Error:[/red] could not read {rich_escape(str(from_file))}: {rich_escape(str(exc))}")
            raise typer.Exit(1)

    # A blank replacement erases the whole memory, and the two ways to arrive at one
    # — a stray empty argument, or a --from-file that was never written — are both
    # mistakes rather than an intent to erase.
    memory = memory.strip()
    if not memory:
        source = f"{rich_escape(str(from_file))} is empty" if from_file is not None else "the replacement text is empty"
        err.print(f"[red]Error:[/red] {source}; that would erase your whole memory.")
        err.print("Pass the text you want stored, or use [bold]tl memory add[/bold] to change one thing at a time.")
        raise typer.Exit(1)

    client = get_client()
    try:
        data = client.post("/memory", json_body={"memory": memory})
        output_single(data, fmt)
        # A replacement past the size limit is kept only up to it. The stored length
        # is in the output either way, but nothing there says text went missing.
        stored = data.get("profile_memory")
        if isinstance(stored, str) and len(stored) < len(memory):
            err.print(
                f"[bold yellow]Warning:[/bold yellow] [yellow]stored {len(stored):,} of "
                f"{len(memory):,} characters — the rest was past the size limit.[/yellow]"
            )
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
