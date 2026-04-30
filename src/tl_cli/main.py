"""TL CLI — ThoughtLeaders command-line interface.

Query sponsorship data, channels, brands, and intelligence.
"""

import sys
import traceback

import typer
from rich.console import Console

from tl_cli import __version__
from tl_cli import config as tl_config
from tl_cli.auth.commands import app as auth_app
from tl_cli.commands.ask import app as ask_app
from tl_cli.commands.balance import app as balance_app
from tl_cli.commands.changelog import changelog_command
from tl_cli.commands.brands import app as brands_app
from tl_cli.commands.channels import app as channels_app
from tl_cli.commands.comments import app as comments_app
from tl_cli.commands.db import app as db_app
from tl_cli.commands.deals import app as deals_app
from tl_cli.commands.matches import app as matches_app
from tl_cli.commands.proposals import app as proposals_app
from tl_cli.commands.recommender import app as recommender_app
from tl_cli.commands.sponsorships import app as sponsorships_app
from tl_cli.commands.describe import app as describe_app
from tl_cli.commands.schema import app as schema_app
from tl_cli.commands.doctor import app as doctor_app
from tl_cli.commands.reports import app as reports_app
from tl_cli.commands.setup import app as setup_app
from tl_cli.commands.snapshots import app as snapshots_app
from tl_cli.commands.uploads import app as uploads_app
from tl_cli.commands.whoami import app as whoami_app

app = typer.Typer(
    name="tl",
    help=f"ThoughtLeaders CLI v{__version__} — query sponsorship data, channels, brands, and intelligence.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def version_callback(value: bool) -> None:
    if value:
        print(f"tl-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version",
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Show detailed error information",
    ),
) -> None:
    """ThoughtLeaders CLI."""
    tl_config.debug = debug

    # Skip hints/warnings for setup commands
    import sys
    if "setup" not in sys.argv:
        # First-run hint
        from tl_cli.auth.token_store import load_tokens
        tokens = load_tokens()
        if not tokens:
            err = Console(stderr=True)
            err.print("[dim]Welcome to tl-cli! Get started:[/dim]")
            err.print("[dim]  tl auth login          # authenticate[/dim]")
            err.print("[dim]  tl setup claude        # install Claude Code plugin[/dim]")
            err.print("[dim]  tl setup opencode      # install OpenCode skill[/dim]")
            err.print()

        from tl_cli.commands.setup import check_plugin_version
        for warn in check_plugin_version():
            Console(stderr=True).print(f"[yellow]{warn}[/yellow]")


# System
app.add_typer(auth_app, name="auth")
app.add_typer(setup_app, name="setup")

# Data commands (primary interface)
app.add_typer(sponsorships_app, name="sponsorships")
app.add_typer(matches_app, name="matches")
app.add_typer(proposals_app, name="proposals")
app.add_typer(deals_app, name="deals")
app.add_typer(uploads_app, name="uploads")
app.add_typer(channels_app, name="channels")
app.add_typer(brands_app, name="brands")
app.add_typer(recommender_app, name="recommender")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(reports_app, name="reports")
app.add_typer(comments_app, name="comments")
app.add_typer(db_app, name="db")

# Discoverability
app.add_typer(describe_app, name="describe")
app.add_typer(schema_app, name="schema")
app.add_typer(balance_app, name="balance")
app.add_typer(doctor_app, name="doctor")
app.add_typer(whoami_app, name="whoami")

# `changelog` is a single command (not a sub-typer) so positional version args
# don't get interpreted as subcommand names.
app.command(
    name="changelog",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(changelog_command)

# AI fallback
app.add_typer(ask_app, name="ask")


@app.command(name="update")
def update_command() -> None:
    """Check for a newer version and upgrade if one is available."""
    from tl_cli.self_update import force_upgrade
    force_upgrade()
    raise typer.Exit()


def cli() -> None:
    """Entry point that wraps the Typer app with top-level error handling.

    The `finally` block runs the post-command version check for pipx/uv
    installs on every exit path — normal return, typer's SystemExit, or
    the sys.exit(1) in the error branch. Silent on failure.
    """
    from tl_cli.self_update import check_and_upgrade
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        if tl_config.debug:
            traceback.print_exc(file=sys.stderr)
        else:
            Console(stderr=True).print(f"[red]Error:[/red] {exc}")
            Console(stderr=True).print("[dim]Run with --debug for details.[/dim]")
        sys.exit(1)
    finally:
        if "update" not in sys.argv:
            check_and_upgrade()


if __name__ == "__main__":
    cli()
