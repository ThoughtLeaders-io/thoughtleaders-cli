"""tl doctor — Health check for auth, connectivity, and version."""

import platform
import shutil
import statistics
import time

import typer
from rich.console import Console
from rich.table import Table

from tl_cli import __version__
from tl_cli.auth.token_store import load_tokens
from tl_cli.client.errors import ApiError
from tl_cli.client.http import get_client
from tl_cli.config import get_config

# Free, side-effect-free GET endpoints we time. Picked to cover the auth
# path (whoami, balance), public-no-auth path (pricing), and the bigger
# payloads (describe, changelog). All cost zero credits.
_LATENCY_ENDPOINTS: tuple[str, ...] = (
    "/balance",
    "/whoami",
    "/pricing",
    "/describe",
    "/changelog",
)
_LATENCY_ITERATIONS = 3

# Helper tools that AI agents using `tl --json` output frequently reach for.
# Not required, but life is much better with them.
_RECOMMENDED_TOOLS: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        "jq",
        "JSON processor — pipe `tl … --json` into `jq` for filtering/projection.",
        {
            "Linux": "apt install jq  /  dnf install jq  /  pacman -S jq",
            "Darwin": "brew install jq",
            "Windows": "winget install jqlang.jq",
        },
    ),
    (
        "rg",
        "ripgrep — fast text search across CLI output, transcripts, and the codebase.",
        {
            "Linux": "apt install ripgrep  /  dnf install ripgrep  /  pacman -S ripgrep",
            "Darwin": "brew install ripgrep",
            "Windows": "winget install BurntSushi.ripgrep.MSVC",
        },
    ),
    (
        "yq",
        "YAML/TOML processor — `jq` for non-JSON formats, useful when reading config or `--md` output.",
        {
            "Linux": "apt install yq  /  dnf install yq  /  pacman -S go-yq  (or `pip install yq`)",
            "Darwin": "brew install yq",
            "Windows": "winget install MikeFarah.yq",
        },
    ),
    (
        "duckdb",
        "Embedded analytical SQL — query `tl … --csv` / `--json` files locally without setting up a database.",
        {
            "Linux": "https://duckdb.org/docs/installation/  (or `pip install duckdb`)",
            "Darwin": "brew install duckdb",
            "Windows": "winget install DuckDB.cli",
        },
    ),
)

app = typer.Typer(help="Health check (auth, connectivity, version)")
console = Console()


def _collect_latency_samples(client, samples_by_endpoint: dict[str, list[float]]) -> None:
    """Hit each free endpoint up to _LATENCY_ITERATIONS times and record
    wall-clock latencies. Endpoints that 404 (older server) are dropped
    silently — they just don't appear in the table.
    """
    for path in _LATENCY_ENDPOINTS:
        # The initial /balance call already produced one sample; top it up
        # so every endpoint has the same call count.
        already = len(samples_by_endpoint.get(path, []))
        for _ in range(max(0, _LATENCY_ITERATIONS - already)):
            t0 = time.perf_counter()
            try:
                client.get(path)
            except ApiError as exc:
                if exc.status_code == 404:
                    # Endpoint missing on this server — stop probing it.
                    break
                # Other errors (5xx, 401 after refresh) still produced a
                # round-trip, so the latency is meaningful — record it.
            except Exception:
                # Network failure mid-probe — bail on this endpoint.
                break
            samples_by_endpoint.setdefault(path, []).append((time.perf_counter() - t0) * 1000)


def _print_latency_table(samples_by_endpoint: dict[str, list[float]]) -> None:
    """Render per-endpoint and overall latency stats."""
    rows = [(path, samples) for path, samples in samples_by_endpoint.items() if samples]
    if not rows:
        return

    table = Table(title="API latency (ms)", show_lines=False)
    table.add_column("Endpoint")
    table.add_column("Calls", justify="right")
    table.add_column("Min", justify="right")
    table.add_column("Median", justify="right")
    table.add_column("Max", justify="right")
    for path, samples in rows:
        table.add_row(
            path,
            str(len(samples)),
            f"{min(samples):.0f}",
            f"{statistics.median(samples):.0f}",
            f"{max(samples):.0f}",
        )
    console.print()
    console.print(table)

    all_samples = [s for _, samples in rows for s in samples]
    if len(all_samples) >= 2:
        # Nearest-rank p95 — good enough for a health-check sample of ~15.
        ranked = sorted(all_samples)
        p95 = ranked[min(len(ranked) - 1, int(round(0.95 * len(ranked))) - 1)]
        console.print(
            f"  Overall: median={statistics.median(all_samples):.0f}ms  "
            f"p95={p95:.0f}ms  max={max(all_samples):.0f}ms  "
            f"n={len(all_samples)}"
        )


@app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context) -> None:
    """Check CLI health: version, auth status, API connectivity, credits."""
    console.print(f"\n[bold]tl-cli[/bold] v{__version__}\n")
    config = get_config()
    all_ok = True

    # API URL
    console.print(f"  API:    {config.cli_api_base}")

    # Auth
    tokens = load_tokens()
    if not tokens:
        console.print("  Auth:   [red]not logged in[/red]")
        all_ok = False
    elif tokens.is_expired:
        console.print(f"  Auth:   [yellow]token expired[/yellow] ({tokens.email})")
        all_ok = False
    else:
        console.print(f"  Auth:   [green]ok[/green] ({tokens.email})")

    # Connectivity + balance + latency timing. The first /balance call
    # doubles as the connectivity probe; subsequent calls feed the
    # latency stats table that's printed at the end of the report.
    samples_by_endpoint: dict[str, list[float]] = {}
    if tokens and not tokens.is_expired:
        client = get_client()
        try:
            try:
                t0 = time.perf_counter()
                data = client.get("/balance")
                samples_by_endpoint.setdefault("/balance", []).append((time.perf_counter() - t0) * 1000)
                balance_val = data.get("balance", "?")
                console.print(f"  API:    [green]connected[/green]")
                console.print(f"  Credits: {balance_val}")
            except ApiError as e:
                console.print(f"  API:    [red]error ({e.status_code})[/red]")
                all_ok = False
            except Exception:
                console.print(f"  API:    [red]unreachable[/red]")
                all_ok = False

            # Pad /balance to N calls and time the remaining free endpoints.
            # The table itself is printed at the bottom, just above the verdict.
            if samples_by_endpoint.get("/balance"):
                _collect_latency_samples(client, samples_by_endpoint)
        finally:
            client.close()
    else:
        console.print("  API:    [dim]skipped (not authenticated)[/dim]")

    # Plugin/skill versions
    from tl_cli.commands.setup import check_plugin_version
    warnings = check_plugin_version()
    if warnings:
        for warn in warnings:
            console.print(f"  Plugin: [yellow]{warn}[/yellow]")
        all_ok = False
    else:
        console.print("  Plugin: [green]ok[/green]")

    # Recommended companion tools (jq, rg). Missing tools are advisory — they
    # don't flip all_ok to false.
    system = platform.system()
    missing: list[tuple[str, str, str | None]] = []
    for name, purpose, install_hints in _RECOMMENDED_TOOLS:
        if shutil.which(name):
            console.print(f"  {name}:     [green]found[/green]")
        else:
            hint = install_hints.get(system)
            console.print(f"  {name}:     [yellow]not found[/yellow]")
            missing.append((name, purpose, hint))

    if missing:
        console.print()
        console.print("[bold]Recommended tools to install:[/bold]")
        for name, purpose, hint in missing:
            console.print(f"  [cyan]{name}[/cyan] — {purpose}")
            if hint:
                console.print(f"    Install: {hint}")

    _print_latency_table(samples_by_endpoint)

    console.print()
    if all_ok:
        console.print("[green]Everything looks good.[/green]")
    else:
        console.print("[yellow]Issues found.[/yellow]")
