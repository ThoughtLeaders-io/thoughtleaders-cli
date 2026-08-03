"""tl memory — read and update your profile memory.

`profile_memory` is the free-text summary of who you are and what you want from
sponsorships. The onboarding interview writes it first; these commands are how it
stays current afterwards.
"""

from pathlib import Path

import typer
from rich.console import Console

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output_single

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Your profile memory (show; add a fact; replace)")


@app.command("show")
def show_cmd(
    profile_id: int = typer.Option(None, "--profile-id", help="Another profile's memory (full-access only)"),
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

    The server merges it into what's already there — keeping everything still
    true and replacing only what the new fact contradicts. Always writes to your
    own profile.

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
        data = client.post("/memory", json_body={"fact": fact.strip()})
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("set")
def set_cmd(
    memory: str = typer.Argument(None, help="The full replacement text"),
    from_file: Path = typer.Option(None, "--from-file", help="Read the replacement text from a file"),
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

    if (memory is None) == (from_file is None):
        err.print("[red]Error:[/red] pass either the replacement text or --from-file, not both.")
        raise typer.Exit(1)

    if from_file is not None:
        try:
            memory = from_file.read_text(encoding="utf-8")
        except OSError as exc:
            err.print(f"[red]Error:[/red] could not read {from_file}: {exc}")
            raise typer.Exit(1)

    client = get_client()
    try:
        data = client.post("/memory", json_body={"memory": memory})
        output_single(data, fmt)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
