"""Tests for PKCE and token storage."""

import httpx
from typer.testing import CliRunner

from tl_cli.auth import commands as auth_commands
from tl_cli.auth import login as auth_login
from tl_cli.auth.commands import app as auth_app
from tl_cli.auth.login import revoke_refresh_token
from tl_cli.auth.pkce import generate_pkce_pair
from tl_cli.auth.token_store import KIND_API_KEY, KIND_BEARER, StoredTokens

runner = CliRunner()


class TestPKCE:
    def test_generates_pair(self):
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) > 40
        assert len(challenge) > 20
        assert verifier != challenge

    def test_different_each_time(self):
        v1, c1 = generate_pkce_pair()
        v2, c2 = generate_pkce_pair()
        assert v1 != v2
        assert c1 != c2


class TestStoredTokens:
    def test_roundtrip_json(self):
        tokens = StoredTokens(
            access_token="abc",
            refresh_token="def",
            expires_at=9999999999.0,
            email="test@example.com",
        )
        json_str = tokens.to_json()
        restored = StoredTokens.from_json(json_str)
        assert restored.access_token == "abc"
        assert restored.refresh_token == "def"
        assert restored.email == "test@example.com"

    def test_is_expired(self):
        tokens = StoredTokens(
            access_token="abc", refresh_token=None, expires_at=0.0
        )
        assert tokens.is_expired

    def test_not_expired(self):
        tokens = StoredTokens(
            access_token="abc", refresh_token=None, expires_at=9999999999.0
        )
        assert not tokens.is_expired


class TestStoredTokensKind:
    def test_default_kind_is_bearer(self):
        tokens = StoredTokens(access_token="x", refresh_token=None, expires_at=9e9)
        assert tokens.kind == KIND_BEARER
        assert not tokens.is_api_key

    def test_api_key_never_expires(self):
        tokens = StoredTokens(
            access_token="k", refresh_token=None, expires_at=0.0, kind=KIND_API_KEY,
        )
        assert tokens.is_api_key
        # 0.0 would mark a bearer token as expired; API keys ignore expiry.
        assert not tokens.is_expired

    def test_kind_roundtrips_through_json(self):
        tokens = StoredTokens(
            access_token="k", refresh_token=None, expires_at=0.0,
            email="user@example.com", kind=KIND_API_KEY,
        )
        restored = StoredTokens.from_json(tokens.to_json())
        assert restored.kind == KIND_API_KEY
        assert restored.is_api_key
        assert restored.email == "user@example.com"

    def test_legacy_payload_without_kind_defaults_to_bearer(self):
        # Pre-API-key clients wrote payloads with no `kind` field. Loading
        # those must still produce a working bearer token.
        legacy = '{"access_token": "x", "refresh_token": "y", "expires_at": 1.0, "email": "e"}'
        restored = StoredTokens.from_json(legacy)
        assert restored.kind == KIND_BEARER
        assert not restored.is_api_key


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class TestRevokeRefreshToken:
    def test_returns_true_on_200(self, monkeypatch) -> None:
        monkeypatch.setattr(auth_login.httpx, "post", lambda *a, **k: _FakeResponse(200))
        assert revoke_refresh_token("rt") is True

    def test_returns_false_on_non_200(self, monkeypatch) -> None:
        monkeypatch.setattr(auth_login.httpx, "post", lambda *a, **k: _FakeResponse(400))
        assert revoke_refresh_token("rt") is False

    def test_swallows_network_error(self, monkeypatch) -> None:
        def boom(*a, **k):
            raise httpx.ConnectError("offline")
        monkeypatch.setattr(auth_login.httpx, "post", boom)
        # Must not raise — logout has to proceed offline.
        assert revoke_refresh_token("rt") is False


class TestLogoutCommand:
    def _patch(self, monkeypatch, tokens):
        calls = {"revoked": None, "cleared": False}
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        monkeypatch.setattr(auth_commands, "clear_tokens", lambda: calls.__setitem__("cleared", True))
        monkeypatch.setattr(auth_commands, "revoke_refresh_token", lambda rt: calls.__setitem__("revoked", rt) or True)
        return calls

    def test_bearer_logout_revokes_then_clears(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=None, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] == "rt"   # revoked with the stored refresh token
        assert calls["cleared"] is True   # local tokens still cleared

    def test_api_key_logout_skips_revoke(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="k", refresh_token=None, expires_at=None, email=None, kind=KIND_API_KEY)
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] is None   # no refresh token → no Auth0 call
        assert calls["cleared"] is True

    def test_logged_out_already_just_clears(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, None)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] is None
        assert calls["cleared"] is True
