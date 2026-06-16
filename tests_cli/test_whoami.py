"""Read-only: `tl whoami` round-trips against the live API."""


def test_whoami_returns_user_and_org(tl_json):
    data = tl_json("whoami")
    assert isinstance(data.get("user"), dict), data
    assert data["user"].get("email"), "whoami should return the caller's email"
    assert isinstance(data.get("organization"), dict), "whoami should return an organization block"
