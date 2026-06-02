"""tl schema — Show raw-db schema documentation for `tl db pg|fb|es`."""

import json
import re

import typer
from tl_cli._typer_utils import AlphaSortedTyperGroup
import yaml
from pytoon import encode as toon_encode
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.tree import Tree

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client

app = typer.Typer(cls=AlphaSortedTyperGroup, help="Show schema documentation for raw db queries (`tl db pg|fb|es`)")
console = Console()

# Pulls the YAML body out of the server's ```yaml … ``` fenced block. Any
# non-YAML preface (e.g. error / empty-set markdown) won't match and is
# rendered through the markdown fallback path.
_YAML_FENCE_RE = re.compile(r'```yaml\n(.*?)\n```', re.DOTALL)


def _try_render_yaml_tree(content: str) -> bool:
    """Render the YAML schema as a Rich Tree, one tree per table.

    Returns True if rendering succeeded. Returns False on any failure
    (no fence, parse error, unexpected shape) so the caller falls back
    to plain markdown rendering.
    """
    match = _YAML_FENCE_RE.search(content)
    if not match:
        return False
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict) or not data:
        return False

    rendered = False
    for table_name, fields in data.items():
        if not isinstance(fields, dict):
            continue
        rendered = True

        # Table-level metadata sits alongside columns under `__`-prefixed
        # keys; surface them in the tree label, never as children.
        table_comment = fields.get('__comment')
        primary_index = fields.get('__primary_index')
        label = Text()
        label.append(str(table_name), style='bold cyan')
        if table_comment:
            label.append(f'  — {table_comment}', style='italic dim')
        if primary_index:
            label.append(f'  — primary index {primary_index}', style='italic dim')

        tree = Tree(label, guide_style='dim')
        for fname, fval in fields.items():
            if isinstance(fname, str) and fname.startswith('__'):
                continue
            if isinstance(fval, dict):
                ftype = str(fval.get('type', '?'))
                fcomment = fval.get('comment')
            else:
                ftype = str(fval)
                fcomment = None
            line = Text()
            line.append(str(fname), style='yellow')
            line.append(': ')
            line.append(ftype, style='green')
            if fcomment:
                line.append(f'  — {fcomment}', style='dim')
            tree.add(line)
        console.print(tree)
        console.print()

    return rendered


def _show(db: str, json_output: bool, table: str | None = None, toon_output: bool = False) -> None:
    client = get_client()
    try:
        params = {"table": table} if table else {}
        data = client.get(f"/raw/{db}/schema", params=params)
        if toon_output:
            print(toon_encode(data))
            return
        if json_output:
            print(json.dumps(data, indent=2, default=str))
            return
        content = data.get("content", "")
        if console.is_terminal:
            # PG/FB output is a fenced YAML mapping; render as a Rich Tree
            # for terminals. ES is still markdown prose, and error / empty
            # responses also have no fence — both fall through to the
            # markdown renderer.
            if db in ("pg", "fb") and _try_render_yaml_tree(content):
                return
            console.print(Markdown(content))
        else:
            print(content)
    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("pg")
def pg_cmd(
    table: str = typer.Argument(None, help="Optional table name. When given, prints only that table's section in the same markdown format."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show PostgreSQL schema reference (for `tl db pg`).

    With no argument: lists every table visible to your role.
    With a table name: prints only that table's column listing.

    **Strongly preferred for single-table lookups.** Listing every
    table just to read one is wasteful — pass the table name and the
    server returns only that section.

    Examples:
        tl schema pg
        tl schema pg thoughtleaders_channel
        tl schema pg thoughtleaders_adlink --json
    """
    _show("pg", json_output, table=table, toon_output=toon_output)


@app.command("fb")
def fb_cmd(
    table: str = typer.Argument(None, help="Optional table name (`article_metrics` or `channel_metrics`). When given, prints only that table's section."),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show Firebolt schema (live: tables and column types) for `tl db fb`.

    With no argument: lists both accepted tables.
    With a table name: prints only that table's columns + primary index.

    **Strongly preferred for single-table lookups.** Pass the table
    name to skip the other one.

    Examples:
        tl schema fb
        tl schema fb article_metrics
        tl schema fb channel_metrics --json
    """
    _show("fb", json_output, table=table, toon_output=toon_output)


@app.command("es")
def es_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show Elasticsearch document shape for `tl db es`."""
    _show("es", json_output, toon_output=toon_output)
