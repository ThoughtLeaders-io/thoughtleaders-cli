"""Tests for the HTTP client's auth-header selection.

Covers the three credential sources TLClient knows about:
  - TL_API_KEY env var (always tagged X-TL-Auth: API-KEY)
  - Stored API key (kind=api_key)
  - Stored bearer token (kind=bearer, OAuth2 default)
"""

from unittest.mock import patch

from tl_cli.auth.token_store import KIND_API_KEY, KIND_BEARER, StoredTokens
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
