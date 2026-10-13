"""tl agent — the AI agent you open ThoughtLeaders skills in.

A skill handed over from a ThoughtLeaders surface (the Chrome extension's skill
buttons, the web app's export door) is counted as finished when it reports back
here with its slug and how it ended.
"""

import typer
from rich.console import Console

from tl_cli._typer_utils import AlphaSortedTyperGroup
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format, output_single

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Your AI agent: report a skill it ran as finished (free)")

OUTCOMES = ("completed", "no_results", "failed")
NO_RUN_CODE = "run_not_found"


@app.command("complete")
def complete_cmd(
    skill: str = typer.Argument(..., help="The skill's slug, e.g. tl-views-guarantee"),
    outcome: str = typer.Option("completed", "--outcome", help="How the run ended: completed, no_results or failed"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Report that a skill opened from a ThoughtLeaders surface has finished.

    Skills call this as their last step. Only a skill opened from a ThoughtLeaders
    surface has a run to close; one started by hand is simply not counted, and
    this command says so and exits cleanly, so a skill's own result is never
    lost over it.

    Examples:
        tl agent complete tl-views-guarantee
        tl agent complete tl-channel-authenticity --outcome no_results
        tl agent complete tl-brand-creator-connection --outcome failed
    """
    fmt = detect_format(json_output, False, False, toon_output)
    err = Console(stderr=True)
    if outcome not in OUTCOMES:
        err.print(f"[red]Error:[/red] --outcome must be one of: {', '.join(OUTCOMES)}.")
        raise typer.Exit(1)

    client = get_client()
    try:
        data = client.post("/agent/complete", json_body={"skill": skill, "outcome": outcome})
        output_single(data, fmt)
    except ApiError as e:
        if e.status_code == 404 and isinstance(e.raw, dict) and e.raw.get("code") == NO_RUN_CODE:
            err.print(f"[dim]No open run of {skill} from a ThoughtLeaders surface; nothing to report.[/dim]")
            return
        handle_api_error(e)
    finally:
        client.close()
