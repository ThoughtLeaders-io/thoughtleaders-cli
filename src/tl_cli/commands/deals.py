"""tl deals — Shortcut for contractually agreed-upon sponsorships."""

import typer

from tl_cli.commands.sponsorships import list_or_show
from tl_cli.output.formatter import detect_format

app = typer.Typer(help="Deals — agreed-upon sponsorships (shortcut for sponsorships status:deal)")


@app.callback(invoke_without_command=True)
def deals(
    ctx: typer.Context,
    args: list[str] = typer.Argument(None, help="ID or filters (key:value pairs)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    csv_output: bool = typer.Option(False, "--csv", help="CSV output"),
    md_output: bool = typer.Option(False, "--md", help="Markdown output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Raw JSON data only"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
) -> None:
    """List deals (agreed-upon sponsorships) or show one by ID.

    Examples:
        tl deals                          # List recent deals
        tl deals 12345                    # Show deal #12345
        tl deals brand:"Nike"             # Filter deals
    """
    if ctx.invoked_subcommand is not None:
        return

    fmt = detect_format(json_output, csv_output, md_output, quiet)
    list_or_show(args or [], fmt, limit, offset, default_status="deal", title="Deals")
