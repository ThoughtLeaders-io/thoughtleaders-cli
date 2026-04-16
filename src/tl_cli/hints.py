"""Detail-view CTA hints, personalized via whoami."""

from tl_cli.client.http import TLClient


def detail_hint(
    client: TLClient,
    *,
    brand: str | None = None,
    channel: str | None = None,
) -> str | None:
    """Build a CTA hint for a detail view.

    - Sponsorship detail: both brand and channel come from the record.
    - Channel detail: channel from the record, brand = user's org (if buyer).
    - Brand detail: brand from the record, channel = user's org (if seller).

    Returns None when both sides can't be determined.
    """
    _u = "[underline]"
    _uu = "[/underline]"
    email = f"{_u}info@thoughtleaders.io{_uu}"

    if brand and channel:
        return (
            f"We can make the sponsorship between {_u}{brand}{_uu} and {_u}{channel}{_uu} work!"
            f" Contact us at {email}"
        )

    # Need the counterparty from whoami
    try:
        data = client.get("/whoami")
    except Exception:
        return None

    flags = data.get("profile", {}).get("flags", [])
    org = data.get("organization", {}).get("name")
    if not org:
        return None

    if channel and not brand and "advertiser" in flags:
        return (
            f"We can make the sponsorship between {_u}{org}{_uu} and {_u}{channel}{_uu} work!"
            f" Contact us at {email}"
        )

    if brand and not channel and "publisher" in flags:
        return (
            f"We can make the sponsorship between {_u}{brand}{_uu} and {_u}{org}{_uu} work!"
            f" Contact us at {email}"
        )

    return None
