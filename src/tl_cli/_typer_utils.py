"""Shared Typer customizations for the tl CLI.

The single export here, ``AlphaSortedTyperGroup``, makes ``--help`` render
its subcommands alphabetically instead of in registration order. It is
applied via ``cls=AlphaSortedTyperGroup`` on every ``typer.Typer(...)``
instantiation in the project so the behavior is consistent at every help
level (``tl --help``, ``tl brands --help``, ``tl db --help``, etc.).
"""

import typer
from typer.core import TyperGroup


class AlphaSortedTyperGroup(TyperGroup):
    """Render subcommands in alphabetical order on ``--help``.

    Typer / Click default ``list_commands`` to insertion order; users
    looking at long help listings want them sorted so the command they
    are after is easy to find.
    """

    def list_commands(self, ctx: typer.Context) -> list[str]:
        return sorted(super().list_commands(ctx))
