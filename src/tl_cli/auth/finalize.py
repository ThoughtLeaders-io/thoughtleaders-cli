"""Server-side signup finalize, called once per login.

After Auth0 returns a valid token the CLI asks the server whether an
account exists for the email. If yes, this is a no-op. If no, the CLI
prompts for a persona (Media Buyer or Creator) and POSTs it back; the
server creates the User, Organization, Profile and CreditAccount.

Errors here never abort login — the user can always retry the prompt
on the next call. We do print a clear message so it's obvious whether
the account is fully set up.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.prompt import Prompt

from tl_cli.client.errors import ApiError
from tl_cli.client.http import get_client

console = Console(stderr=True)

PERSONA_LABEL_TO_KEY = {
    "Media Buyer": "media_buyer",
    "Creator": "creator",
}


def finalize_signup() -> None:
    """POST /auth/finalize, prompting for persona if the server asks for one."""
    client = get_client()
    try:
        # First call: no body. Server tells us whether persona is required.
        try:
            result = client.post("/auth/finalize", {})
        except ApiError as exc:
            if exc.status_code == 400 and isinstance(exc.raw, dict) and exc.raw.get("code") == "persona_required":
                result = _prompt_and_finalize(client, exc.raw.get("allowed_personas") or [])
            elif exc.status_code == 404:
                # Server predates this endpoint — silently skip; legacy
                # accounts already exist and don't need provisioning.
                return
            else:
                console.print(f"[yellow]Could not finalize signup: {exc.detail}[/yellow]")
                return

        if result.get("created"):
            org = result.get("organization", {})
            console.print(
                f"[green]Account created for {org.get('name', 'your organization')}.[/green] "
                "Run [bold]tl balance[/bold] to see your starter credits."
            )
    finally:
        client.close()


def _prompt_and_finalize(client, allowed: list[str]) -> dict:
    """Prompt the user for a persona, then retry /auth/finalize."""
    console.print()
    console.print("[bold]Welcome to ThoughtLeaders![/bold] We need one more detail to set up your account.")
    console.print("  [cyan]1[/cyan] — Media Buyer (brands and agencies buying sponsorships)")
    console.print("  [cyan]2[/cyan] — Creator (channels selling sponsorships)")

    persona_key: str | None = None
    while persona_key is None:
        choice = Prompt.ask("I am a", choices=["1", "2"], default="1", console=console)
        candidate = "media_buyer" if choice == "1" else "creator"
        if allowed and candidate not in allowed:
            console.print(f"[yellow]Server rejects persona '{candidate}'. Allowed: {', '.join(allowed)}.[/yellow]")
            continue
        persona_key = candidate

    org_name = Prompt.ask(
        "Organization name (optional, leave blank to use your email)",
        default="",
        console=console,
    ).strip()

    body = {"persona": persona_key}
    if org_name:
        body["organization_name"] = org_name

    try:
        return client.post("/auth/finalize", body)
    except ApiError as exc:
        console.print(f"[red]Signup failed:[/red] {exc.detail}")
        raise typer.Exit(1)
