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
        assert "X-TL-Signed-In-At" not in headers   # legacy store: sign-in time unknown

    def test_stored_bearer_token_carries_the_sign_in_time(self):
        stored = StoredTokens(
            access_token="bearer-jwt-xyz",
            refresh_token="rt",
            expires_at=9_999_999_999.0,
            kind=KIND_BEARER,
            signed_in_at=1_700_000_000.7,
        )
        client = _make_client(api_key_env=None)
        try:
            with patch("tl_cli.client.http.load_tokens", return_value=stored):
                headers = client._auth_headers()
        finally:
            client.close()
        # Whole seconds: the server compares it with a sign-out moment.
        assert headers["X-TL-Signed-In-At"] == "1700000000"


class TestSignedOutElsewhere:
    """A 401 carrying code=signed_out means the user ended this session on
    another surface: the client must drop its credentials, not refresh."""

    def _stored(self, kind=KIND_BEARER):
        return StoredTokens(
            access_token="old-jwt", refresh_token="rt" if kind == KIND_BEARER else None,
            expires_at=9_999_999_999.0, kind=kind,
        )

    def _resp(self, status, body):
        req = httpx.Request("GET", "https://x/whoami")
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=req)
        return httpx.Response(status, json=body, request=req)

    def _run(self, *responses, stored=None, api_key_env=None, refreshed_headers=None):
        """Feed `responses` to successive requests; return (calls, error)."""
        calls = {"forgot": None, "refreshed": False, "requests": []}
        client = _make_client(api_key_env=api_key_env)
        queue = list(responses)

        def fake_request(method, path, **kwargs):
            calls["requests"].append(kwargs["headers"])
            return queue.pop(0)

        def fake_refresh():
            calls["refreshed"] = True
            return refreshed_headers

        error: ApiError | None = None
        try:
            with (
                patch("tl_cli.client.http.load_tokens", return_value=stored or self._stored()),
                patch.object(client._client, "request", fake_request),
                patch(
                    "tl_cli.client.http.forget_session",
                    lambda rejected_access_token=None, rejected_signed_in_at=None: calls.__setitem__(
                        "forgot", (rejected_access_token, rejected_signed_in_at)
                    ),
                ),
                patch.object(client, "_refresh_and_get_headers", fake_refresh),
            ):
                try:
                    client.get("/whoami")
                except ApiError as e:
                    error = e
        finally:
            client.close()
        return calls, error

    def test_signed_out_drops_the_refused_token_without_refreshing(self):
        body = {"detail": "You signed out of ThoughtLeaders.", "code": "signed_out"}
        calls, error = self._run(self._resp(401, body))
        assert calls["forgot"] == ("old-jwt", None)     # the exact token that was refused
        assert calls["refreshed"] is False
        assert error is not None and error.status_code == 401
        assert error.raw == body

    def test_a_plain_401_still_tries_a_refresh(self):
        calls, error = self._run(self._resp(401, {"detail": "Token has expired"}))
        assert calls["refreshed"] is True
        assert calls["forgot"] is None
        assert error is not None and error.status_code == 401

    def test_a_non_json_401_is_treated_as_a_plain_one(self):
        calls, error = self._run(self._resp(401, "<html>challenge</html>"))
        assert calls["refreshed"] is True
        assert calls["forgot"] is None
        assert error is not None and error.status_code == 401

    def test_signed_out_on_the_retry_is_honoured(self):
        # First 401 is a plain expiry, the refreshed token is then refused as
        # signed out: the verdict is read off the final response, and the
        # session is named by the sign-in time that request carried.
        calls, error = self._run(
            self._resp(401, {"detail": "Token has expired"}),
            self._resp(401, {"detail": "You signed out.", "code": "signed_out"}),
            refreshed_headers={"Authorization": "Bearer fresh-jwt", "X-TL-Signed-In-At": "1700000000"},
        )
        assert calls["refreshed"] is True
        assert calls["forgot"] == ("fresh-jwt", 1700000000.0)
        assert calls["requests"][1]["X-TL-Signed-In-At"] == "1700000000"
        assert error is not None and error.raw["code"] == "signed_out"

    def test_env_api_key_never_refreshes_or_forgets(self):
        calls, error = self._run(
            self._resp(401, {"code": "signed_out"}), api_key_env="ci-key",
        )
        assert calls["refreshed"] is False
        assert calls["forgot"] is None      # the keychain session is not what was refused
        assert error is not None and error.status_code == 401

    def test_stored_api_key_never_refreshes_or_forgets(self):
        calls, error = self._run(
            self._resp(401, {"code": "signed_out"}), stored=self._stored(KIND_API_KEY),
        )
        assert calls["refreshed"] is False
        assert calls["forgot"] is None
        assert error is not None and error.status_code == 401
