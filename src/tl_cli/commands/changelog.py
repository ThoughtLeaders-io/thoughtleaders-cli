"""tl changelog — Show release notes for one or more CLI versions."""

from __future__ import annotations

import json
import sys

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from tl_cli import __version__
from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.self_update import _fetch_latest_version, _version_tuple


def _normalize(v: str) -> str:
    v = v.strip()
    if not v:
        return ''
    return v if v.startswith('v') else f'v{v}'


def _build_request_body(args: list[str]) -> tuple[dict, str | None]:
    """Translate CLI args into the API request body. Returns (body, error_or_none)."""
    if not args:
        # No args: bound the request to either the current version (when up to
        # date) or strictly the gap between current and latest. Never request
        # the full version history.
        latest = _fetch_latest_version()
        current = f'v{__version__}'
        if not latest:
            return {'versions': [current]}, None
        try:
            if _version_tuple(latest) <= _version_tuple(__version__):
                return {'versions': [current]}, None
        except ValueError:
            return {'versions': [current]}, None
        return {'since': current}, None

    if len(args) >= 2 and args[0].lower() == 'since':
        since = _normalize(args[1])
        if not since:
            return {}, "'since' requires a version (e.g. tl changelog since v0.4.10)"
        return {'since': since}, None

    versions = [_normalize(v) for v in args if v.strip()]
    if not versions:
        return {}, 'no valid versions in arguments'
    return {'versions': versions}, None


def _render(data: dict, json_output: bool, md_output: bool) -> None:
    results = data.get('results', []) or []

    if json_output or (not sys.stdout.isatty() and not md_output):
        print(json.dumps(data, indent=2, default=str))
        return

    if not results:
        Console(stderr=True).print('[dim]No changelog entries returned.[/dim]')
        return

    if md_output:
        for entry in results:
            print(f"## {entry.get('version', '?')}")
            date = entry.get('release_date') or ''
            if date:
                print(f"_Released {date}_\n")
            print(entry.get('summary', '').strip() or '_(no summary)_')
            print()
        return

    console = Console()
    for entry in results:
        version = entry.get('version', '?')
        date = entry.get('release_date') or ''
        title = Text(version, style='bold cyan')
        if date:
            title.append(f"  ·  released {date}", style='dim')
        body = entry.get('summary', '').strip() or '_(no summary)_'
        console.print(Panel(Markdown(body), title=title, title_align='left', border_style='cyan'))


def changelog_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, '--json', help='JSON output'),
    md_output: bool = typer.Option(False, '--md', help='Markdown output (good for piping into a doc)'),
) -> None:
    """Show release notes for tl-cli versions.

    Positional arguments are version numbers, or the special form
    `since <version>` to get everything between that version and the latest
    release. With no arguments, shows the current version's notes (or the
    gap from current to latest if you're behind).

    Examples:
        tl changelog                       # current version (or current..latest if outdated)
        tl changelog v0.4.17 v0.4.18       # explicit list
        tl changelog since v0.4.10         # everything from v0.4.10 to latest
        tl changelog --md > CHANGELOG.md   # capture for a doc
    """
    raw_args = [a for a in (ctx.args or []) if a and not a.startswith('-')]
    body, err = _build_request_body(raw_args)
    if err:
        Console(stderr=True).print(f'[red]Error:[/red] {err}')
        raise typer.Exit(2)

    client = get_client()
    try:
        data = client.post('/changelog', json_body=body)
        _render(data, json_output, md_output)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()
