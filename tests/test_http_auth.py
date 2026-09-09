"""Tests for the HTTP client's auth-header selection.

Covers the three credential sources TLClient knows about:
  - TL_API_KEY env var (always tagged X-TL-Auth: API-KEY)
  - Stored API key (kind=api_key)
  - Stored bearer token (kind=bearer, OAuth2 default)
"""

from unittest.mock import patch

import httpx

from tl_cli.auth.token_store import KIND_API_KEY, KIND_BEARER, StoredTokens
from tl_cli.client.errors import ApiError
from tl_cli.client.http import TLClient


def _make_client(api_key_env: str | None = None) -> TLClient:
    """Build a TLClient with the env-var api_key field overridden."""
    client = TLClient()
    client._config.api_key = api_key_env
    return client


class TestAuthHeaders:
    def test_env_api_key_sets_x_tl_auth(self):
        client = _make_client(api_key_env="env-key-123")
        try:
            headers = client._auth_headers()
        finally:
            client.close()
        assert headers["Authorization"] == "Bearer env-key-123"
        assert headers["X-TL-Auth"] == "API-KEY"

    def test_stored_api_key_sets_x_tl_auth(self):
        stored = StoredTokens(
            access_token="stored-key-abc",
            refresh_token=None,
            expires_at=0.0,
            kind=KIND_API_KEY,
        )
        client = _make_client(api_key_env=None)
        try:
            with patch("tl_cli.client.http.load_tokens", return_value=stored):
                headers = client._auth_headers()
        finally:
            client.close()
        assert headers["Authorization"] == "Bearer stored-key-abc"
        assert headers["X-TL-Auth"] == "API-KEY"

    def test_stored_bearer_token_omits_x_tl_auth(self):
        stored = StoredTokens(
            access_token="bearer-jwt-xyz",
            refresh_token=None,
            expires_at=9_999_999_999.0,
            kind=KIND_BEARER,
        )
        client = _make_client(api_key_env=None)
        try:
            with patch("tl_cli.client.http.load_tokens", return_value=stored):
                headers = client._auth_headers()
        finally:
            client.close()
        assert headers["Authorization"] == "Bearer bearer-jwt-xyz"
        assert "X-TL-Auth" not in headers


class TestSignedOutElsewhere:
    """A 401 carrying code=signed_out means the user ended this session on
    another surface: the client must drop its credentials, not refresh."""

    def _stored_bearer(self):
        return StoredTokens(
            access_token="old-jwt", refresh_token="rt", expires_at=9_999_999_999.0, kind=KIND_BEARER,
        )

    def _run(self, body: dict, status: int = 401) -> tuple[dict, ApiError | None]:
        calls = {"forgot": False, "refreshed": False}
        client = _make_client(api_key_env=None)
        response = httpx.Response(status, json=body, request=httpx.Request("GET", "https://x/whoami"))
        error: ApiError | None = None
        try:
            with (
                patch("tl_cli.client.http.load_tokens", return_value=self._stored_bearer()),
                patch.object(client._client, "request", return_value=response),
                patch("tl_cli.client.http.forget_session", lambda: calls.__setitem__("forgot", True)),
                patch.object(
                    client, "_refresh_and_get_headers",
                    lambda: calls.__setitem__("refreshed", True) or None,
                ),
            ):
                try:
                    client.get("/whoami")
                except ApiError as e:
                    error = e
        finally:
            client.close()
        return calls, error

    def test_signed_out_drops_credentials_without_refreshing(self):
        calls, error = self._run({"detail": "You signed out of ThoughtLeaders.", "code": "signed_out"})
        assert calls["forgot"] is True
        assert calls["refreshed"] is False
        assert error is not None and error.status_code == 401
        assert error.raw == {"detail": "You signed out of ThoughtLeaders.", "code": "signed_out"}

    def test_a_plain_401_still_tries_a_refresh(self):
        calls, error = self._run({"detail": "Token has expired"})
        assert calls["refreshed"] is True
        assert calls["forgot"] is False
        assert error is not None and error.status_code == 401
