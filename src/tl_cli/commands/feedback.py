"""tl feedback — Send a markdown-formatted note to the #ai-feedback channel."""

import sys

import typer
from rich.console import Console

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client


app = typer.Typer(help="Send feedback about the CLI to the team (free)")
console = Console(stderr=True)


@app.callback(invoke_without_command=True)
def feedback(
    ctx: typer.Context,
    text: str = typer.Argument(
        None,
        help='Markdown-formatted feedback. Omit to read from stdin (handy for piping or heredocs).',
    ),
) -> None:
    """Send a markdown-formatted note to the ThoughtLeaders team.

    The server prepends your user/org context and posts everything to the
    #ai-feedback Slack channel. Slack supports a subset of markdown —
    `*bold*`, `_italic_`, `~strike~`, ``code``, ```fences```, `> quotes`,
    and `<url|label>` links. Standard `**bold**`, `[text](url)` links,
    and `#` headers render as plain text in Slack.

    Examples:
        tl feedback "The new *find* command is great, but it should also accept channel IDs from URLs."
        echo "long note here" | tl feedback
        tl feedback <<< "$(cat note.md)"
    """
    if ctx.invoked_subcommand is not None:
        return

    body = text
    if body is None:
        if sys.stdin.isatty():
            console.print('[red]Error:[/red] no feedback text provided.')
            console.print('Pass the text as an argument, or pipe it via stdin.')
            raise typer.Exit(1)
        body = sys.stdin.read()

    body = (body or '').strip()
    if not body:
        console.print('[red]Error:[/red] feedback text is empty.')
        raise typer.Exit(1)

    client = get_client()
    try:
        client.post('/feedback', json_body={'text': body})
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()

    console.print('[green]Thanks![/green] Your feedback was sent to the team.')
