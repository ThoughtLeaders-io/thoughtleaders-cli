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
    def _patch(self, monkeypatch, tokens, *, tty=True, browser_opens=True):
        calls = {"revoked": None, "cleared": False, "opened": None}
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        monkeypatch.setattr(auth_commands, "clear_tokens", lambda: calls.__setitem__("cleared", True))
        monkeypatch.setattr(auth_commands, "revoke_refresh_token", lambda rt: calls.__setitem__("revoked", rt) or True)
        monkeypatch.setattr(
            auth_commands.webbrowser, "open",
            lambda url: calls.__setitem__("opened", url) or browser_opens,
        )
        monkeypatch.setattr(auth_commands, "_interactive", lambda: tty)
        return calls

    def _web_logout(self):
        return auth_commands.web_logout_url(auth_commands.get_config())

    def test_bearer_logout_revokes_clears_and_ends_web_session(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=None, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] == "rt"   # revoked with the stored refresh token
        assert calls["cleared"] is True   # local tokens still cleared
        # Logout is for every surface: the platform's /logout is driven in the browser.
        assert calls["opened"] == self._web_logout()
        assert "web platform" in result.output

    def test_api_key_logout_skips_revoke_but_still_ends_web_session(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="k", refresh_token=None, expires_at=None, email=None, kind=KIND_API_KEY)
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] is None   # no refresh token → no Auth0 call
        assert calls["cleared"] is True
        assert calls["opened"] == self._web_logout()

    def test_logged_out_already_just_clears(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, None)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] is None
        assert calls["cleared"] is True

    def test_local_leaves_other_surfaces_alone(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=None, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout", "--local"])
        assert result.exit_code == 0
        assert calls["revoked"] == "rt"
        assert calls["cleared"] is True
        assert calls["opened"] is None
        assert "/logout" not in result.output

    def test_no_tty_prints_url_instead_of_opening_browser(self, monkeypatch) -> None:
        # An agent or script must never get a browser window popped at it.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=None, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, tty=False)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["opened"] is None
        assert self._web_logout() in result.output

    def test_browser_refusing_falls_back_to_url(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=None, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, browser_opens=False)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["opened"] == self._web_logout()
        assert self._web_logout() in result.output


class TestStatusCommand:
    def test_quiet_logged_in_prints_nothing(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        result = runner.invoke(auth_app, ["status", "--quiet"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_quiet_logged_out_exits_2_silently(self, monkeypatch) -> None:
        # The Claude Code pre-check hook relies on this exit code.
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: None)
        result = runner.invoke(auth_app, ["status", "--quiet"])
        assert result.exit_code == 2
        assert result.output == ""

    def test_quiet_expired_exits_2_silently(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token=None, expires_at=0.0, email="e@x.com")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        result = runner.invoke(auth_app, ["status", "-q"])
        assert result.exit_code == 2
        assert result.output == ""

    def test_verbose_still_reports(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        result = runner.invoke(auth_app, ["status"])
        assert result.exit_code == 0
        assert "e@x.com" in result.output


class TestLoginCommand:
    def test_method_skips_menu(self, monkeypatch) -> None:
        seen = {}
        monkeypatch.setattr(auth_commands, "login_browser", lambda open_browser=True: seen.setdefault("open", open_browser))
        result = runner.invoke(auth_app, ["login", "--method", "browser", "--no-browser"])
        assert result.exit_code == 0
        assert seen["open"] is False   # --no-browser reached the flow
        assert "How would you like" not in result.output

    def test_method_device(self, monkeypatch) -> None:
        seen = {}
        monkeypatch.setattr(auth_commands, "login_device_code", lambda: seen.setdefault("device", True))
        result = runner.invoke(auth_app, ["login", "-m", "device"])
        assert result.exit_code == 0
        assert seen["device"] is True

    def test_unknown_method_is_an_error(self) -> None:
        result = runner.invoke(auth_app, ["login", "--method", "carrier-pigeon"])
        assert result.exit_code == 1
        assert "Unknown --method" in result.output


class TestCallbackServer:
    def _get(self, port: int, path: str) -> httpx.Response:
        with httpx.Client(follow_redirects=False, timeout=5) as c:
            return c.get(f"http://127.0.0.1:{port}{path}")

    def test_success_redirects_browser_to_platform_signin(self) -> None:
        result = auth_login._CallbackResult()
        server, port = auth_login._start_callback_server(
            result, "st", 0, success_redirect="https://app.example/signin?go=1&from=cli"
        )
        try:
            r = self._get(port, "/callback?code=abc&state=st")
        finally:
            server.shutdown()
        assert r.status_code == 302
        assert r.headers["location"] == "https://app.example/signin?go=1&from=cli"
        assert result.code == "abc"

    def test_without_redirect_serves_close_tab_page(self) -> None:
        result = auth_login._CallbackResult()
        server, port = auth_login._start_callback_server(result, "st", 0)
        try:
            r = self._get(port, "/callback?code=abc&state=st")
        finally:
            server.shutdown()
        assert r.status_code == 200
        assert "close this tab" in r.text
        assert result.code == "abc"

    def test_state_mismatch_never_redirects(self) -> None:
        result = auth_login._CallbackResult()
        server, port = auth_login._start_callback_server(
            result, "st", 0, success_redirect="https://app.example/signin"
        )
        try:
            r = self._get(port, "/callback?code=abc&state=WRONG")
        finally:
            server.shutdown()
        assert r.status_code == 200
        assert result.code is None
        assert result.error


class TestWebUrls:
    def test_urls_derive_from_api_url(self, monkeypatch) -> None:
        monkeypatch.setenv("TL_API_URL", "https://staging.example/")
        cfg = auth_login.get_config()
        assert auth_login.web_signin_url(cfg) == "https://staging.example/signin?go=1&from=cli"
        assert auth_login.web_logout_url(cfg) == "https://staging.example/logout"

    def test_default_auth0_domain_is_the_shared_custom_domain(self, monkeypatch) -> None:
        # One SSO cookie per host: only this host shares the web platform's session.
        monkeypatch.delenv("TL_AUTH0_DOMAIN", raising=False)
        assert auth_login.get_config().auth0_domain == "auth.thoughtleaders.io"
