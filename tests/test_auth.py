"""Tests for PKCE and token storage."""

from tl_cli.auth.pkce import generate_pkce_pair
from tl_cli.auth.token_store import KIND_API_KEY, KIND_BEARER, StoredTokens


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
