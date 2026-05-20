"""tl describe — Schema and filter discovery for resources."""

import json

import typer
from rich.console import Console
from rich.table import Table

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.client.http import get_client
from tl_cli.output.formatter import detect_format

app = typer.Typer(help="Discover available resources, fields, filters, and credit costs")
console = Console()


@app.callback(invoke_without_command=True)
def describe(ctx: typer.Context) -> None:
    """Discover resources, fields, filters, and credit costs (free)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd, json_output=False)


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """List all available resources with credit costs.

    Examples:
        tl describe list
        tl describe list --json
    """
    fmt = detect_format(json_output, False, False, toon_output)

    client = get_client()
    try:
        data = client.get("/describe")

        if fmt == "json":
            print(json.dumps(data, indent=2, default=str))
            return

        _print_resource_list(data)

    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


@app.command("show")
def show_cmd(
    resource: str = typer.Argument(..., help="Resource name (sponsorships, channels, etc.)"),
    filters_only: bool = typer.Option(False, "--filters", help="Show only available filters"),
    fields_only: bool = typer.Option(False, "--fields", help="Show only available fields"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    toon_output: bool = typer.Option(False, "--toon", help="TOON output (token-efficient for LLMs)"),
) -> None:
    """Show fields, filters, and credit costs for a specific resource.

    Examples:
        tl describe show sponsorships
        tl describe show sponsorships --filters
        tl describe show sponsorships --json
    """
    fmt = detect_format(json_output, False, False, toon_output)

    if resource in {"channels", "brands"}:
        notice = (
            f"Examine the database schema with `tl schema pg` and then perform "
            f"a `tl db pg` query on {resource}."
        )
        if fmt == "json":
            print(json.dumps({"resource": resource, "notice": notice}, indent=2))
        else:
            console.print(notice)
        return

    client = get_client()
    try:
        data = client.get(f"/describe/{resource}")

        if fmt == "json":
            target = data
            if filters_only and "filters" in data:
                target = data["filters"]
            elif fields_only and "fields" in data:
                target = data["fields"]
            print(json.dumps(target, indent=2, default=str))
            return

        _print_resource_detail(data, filters_only, fields_only)

    except ApiError as e:
        handle_api_error(e)
    finally:
        client.close()


def _fmt_credits(n: float) -> str:
    """Render a credit count compactly: no trailing zeros, comma grouping >= 1000."""
    if n is None:
        return "-"
    if isinstance(n, (int, float)) and float(n).is_integer():
        return f"{int(n):,}"
    return f"{n:,.2f}".rstrip("0").rstrip(".")


def _modes_block(credits: dict) -> dict:
    """Return `credits.modes` regardless of payload shape.

    New-shape: `credits.modes` is a dict of `{mode: {model, rate, …}}`.
    Legacy fallback: synthesise a minimal `{mode: {model: "?", rate}}` so
    older servers' responses still render the resource row.
    """
    modes = credits.get("modes")
    if isinstance(modes, dict) and modes:
        return modes
    return {
        k: {"model": "?", "rate": v}
        for k, v in credits.items()
        if isinstance(v, (int, float))
    }


def _summarise_modes(credits: dict) -> tuple[str, str, bool]:
    """Return (pricing-model-string, typical-cost-string, has_expensive_warning).

    Compact one-line rendering for the overview table:
      - 'free'                           → "free"
      - 'flat'                           → "<rate> per call"
      - 'linear-per-result' (one mode)   → "<rate> × n  (per result)"
      - 'curve' (one mode, mult=R)       → "curve (×R)"
      - mixed (e.g. channels has detail / history / similar at different rates)
                                         → per-mode "<mode> R" joined with commas

    The typical-cost column uses the n=100 example for curve/per-result and
    the flat rate for flat. Free shows '-'.
    """
    modes = _modes_block(credits)
    if not modes:
        return "-", "-", False

    has_warning = any(m.get("warning") == "expensive" for m in modes.values())

    # Single-mode short rendering
    if len(modes) == 1:
        mode_name, payload = next(iter(modes.items()))
        return _format_single_mode_label(mode_name, payload), _typical_cost(payload), has_warning

    # Multi-mode → compact "<mode> <model-hint>" list
    pieces: list[str] = []
    typical: list[str] = []
    for mode_name, payload in modes.items():
        pieces.append(f"{mode_name} {_format_single_mode_label(mode_name, payload, terse=True)}")
        cost = _typical_cost(payload)
        if cost != "-":
            typical.append(f"{mode_name}: {cost}")
    return ", ".join(pieces), ", ".join(typical) if typical else "-", has_warning


def _format_single_mode_label(mode_name: str, payload: dict, *, terse: bool = False) -> str:
    """Format one mode's pricing-model column cell."""
    model = payload.get("model", "?")
    rate = payload.get("rate", 0)
    if model == "free" or (model == "?" and rate == 0):
        return "free"
    if model == "flat":
        return f"{_fmt_credits(rate)}/call" if terse else f"{_fmt_credits(rate)} per call"
    if model == "linear-per-result":
        return f"{_fmt_credits(rate)}×n" if terse else f"{_fmt_credits(rate)} × n  (per result)"
    if model == "curve":
        return f"curve ×{rate}"
    return f"{model} ({_fmt_credits(rate)})"


def _typical_cost(payload: dict) -> str:
    """Pick the 'typical' example from a mode's examples list."""
    examples = payload.get("examples") or []
    if not examples:
        return "-"
    # Prefer n=100 if present; fall back to the second example, then the last.
    for ex in examples:
        if ex.get("n") == 100:
            return f"n=100 → {_fmt_credits(ex['credits'])}"
    if "n" in examples[0]:
        ex = examples[min(1, len(examples) - 1)]
        return f"n={ex.get('n')} → {_fmt_credits(ex['credits'])}"
    return _fmt_credits(examples[0]["credits"])


def _print_resource_list(data: dict) -> None:
    """Print all available resources."""
    resources = data.get("resources", [])
    has_any_warning = False

    table = Table(title="Available Resources")
    table.add_column("Resource", style="bold cyan")
    table.add_column("Description", overflow="fold")
    table.add_column("Pricing model", overflow="fold")
    table.add_column("Typical cost")

    for r in resources:
        credits = r.get("credits", {})
        model_str, typical_str, has_warning = _summarise_modes(credits)
        has_any_warning = has_any_warning or has_warning
        marker = "[yellow]★[/yellow] " if has_warning else ""
        table.add_row(
            r["name"],
            r.get("description", ""),
            f"{marker}{model_str}",
            typical_str,
        )

    console.print(table)
    if has_any_warning:
        console.print(
            "[yellow]★ expensive[/yellow] — cost scales with --limit / row count. "
            "Run [bold]tl describe show <resource>[/bold] for the formula and examples."
        )


def _print_pricing_section(credits: dict) -> None:
    """Render the per-mode Pricing table on the resource detail view."""
    modes = _modes_block(credits)
    if not modes:
        return

    table = Table(title="Pricing")
    table.add_column("Mode", style="bold")
    table.add_column("Model")
    table.add_column("Examples (credits)", overflow="fold")
    table.add_column("Notes", overflow="fold")

    any_warning = False
    for mode_name, payload in modes.items():
        if payload.get("warning") == "expensive":
            any_warning = True
            mode_cell = f"[yellow]★[/yellow] {mode_name}"
        else:
            mode_cell = mode_name

        model = payload.get("model", "?")
        rate = payload.get("rate", 0)
        formula = payload.get("formula") or model
        examples = payload.get("examples") or []

        if examples and "n" in examples[0]:
            ex_str = "   ".join(f"n={e['n']} → {_fmt_credits(e['credits'])}" for e in examples)
        elif examples:
            ex_str = f"{_fmt_credits(examples[0]['credits'])} per call"
        else:
            ex_str = "-"

        table.add_row(mode_cell, formula, ex_str, payload.get("notes") or "")

    console.print(table)

    if any_warning:
        console.print(
            "\n[yellow]★ expensive[/yellow] — cost scales with --limit / result count. "
            "Estimate using the examples above before running with a large limit."
        )

    # Surface live pg surcharges when the server included them (db resource only).
    surcharges = credits.get("pg_surcharges")
    if isinstance(surcharges, dict) and surcharges:
        sub = Table(title="PG surcharges (live)")
        sub.add_column("Path", style="bold")
        sub.add_column("Surcharge", justify="right")
        for path, val in sorted(surcharges.items()):
            sub.add_row(path, _fmt_credits(val))
        console.print(sub)


def _print_resource_detail(data: dict, filters_only: bool, fields_only: bool) -> None:
    """Print fields and/or filters for a resource."""
    name = data.get("resource", "")
    desc = data.get("description", "")
    credits = data.get("credits", {})

    if not filters_only:
        console.print(f"\n[bold]{name}[/bold] — {desc}\n")
        _print_pricing_section(credits)

        fields = data.get("fields", [])
        if fields:
            table = Table(title="Fields")
            table.add_column("Name", style="bold")
            table.add_column("Type")
            table.add_column("Description", overflow="fold")
            for f in fields:
                table.add_row(f["name"], f.get("type", ""), f.get("description", ""))
            console.print(table)

    if not fields_only:
        filters = data.get("filters", [])
        if filters:
            table = Table(title="Filters")
            table.add_column("Name", style="bold cyan")
            table.add_column("Type")
            table.add_column("Description", overflow="fold")
            table.add_column("Values")
            for f in filters:
                values = ", ".join(f.get("values", [])) if "values" in f else ""
                table.add_row(
                    f["name"],
                    f.get("type", ""),
                    f.get("description", ""),
                    values,
                )
            console.print(table)
