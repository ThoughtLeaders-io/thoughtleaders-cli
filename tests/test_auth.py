"""Tests for PKCE and token storage."""

import httpx
import pytest
from typer.testing import CliRunner

from tl_cli.auth import commands as auth_commands
from tl_cli.auth import login as auth_login
from tl_cli.auth.commands import app as auth_app
from tl_cli.auth.login import revoke_refresh_token
from tl_cli.auth.pkce import generate_pkce_pair
from tl_cli.auth.token_store import KIND_API_KEY, KIND_BEARER, StoredTokens
from tl_cli.client.errors import ApiError, handle_api_error

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

    def test_signed_in_at_roundtrips_and_is_absent_for_legacy_payloads(self):
        tokens = StoredTokens(access_token="x", refresh_token="y", expires_at=1.0, signed_in_at=1700000000.0)
        assert StoredTokens.from_json(tokens.to_json()).signed_in_at == 1700000000.0
        legacy = '{"access_token": "x", "refresh_token": "y", "expires_at": 1.0, "email": "e"}'
        assert StoredTokens.from_json(legacy).signed_in_at is None

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


class _FakeClient:
    def __init__(self, calls, fail=False, refuse=None):
        self.calls, self.fail, self.refuse = calls, fail, refuse

    def post(self, path, json_body=None):
        self.calls["posted"] = path
        if self.fail:
            raise httpx.ConnectError("offline")
        if self.refuse:
            detail, code = self.refuse if isinstance(self.refuse, tuple) else (self.refuse, "signed_out")
            raise ApiError(401, detail, raw={"detail": detail, "code": code})
        return {"signed_out_at": "2026-09-09T00:00:00Z"}

    def close(self):
        pass


class TestLogoutCommand:
    def _patch(self, monkeypatch, tokens, *, tty=True, browser_opens=True, api_down=False, api_refuses=None):
        calls = {"revoked": None, "cleared": False, "opened": None, "posted": None}
        monkeypatch.delenv("TL_API_KEY", raising=False)
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        monkeypatch.setattr(auth_commands, "clear_tokens", lambda: calls.__setitem__("cleared", True))
        monkeypatch.setattr(auth_commands, "revoke_refresh_token", lambda rt: calls.__setitem__("revoked", rt) or True)
        monkeypatch.setattr(
            auth_commands, "open_in_browser",
            lambda url: calls.__setitem__("opened", url) or browser_opens,
        )
        monkeypatch.setattr(auth_commands, "get_client", lambda: _FakeClient(calls, fail=api_down, refuse=api_refuses))
        monkeypatch.setattr(auth_commands, "_interactive", lambda: tty)
        return calls

    def _web_logout(self):
        return auth_commands.web_logout_url(auth_commands.get_config())

    def test_bearer_logout_revokes_clears_and_ends_web_session(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] == "rt"   # revoked with the stored refresh token
        assert calls["cleared"] is True   # local tokens still cleared
        # Logout is for every surface: the platform is told first (so the
        # extension and other CLIs are refused), then its /logout is driven in
        # the browser to end the web session too.
        assert calls["posted"] == "/auth/sign-out"
        assert calls["opened"] == self._web_logout()
        assert "web platform" in result.output

    def test_api_key_logout_only_clears_the_key(self, monkeypatch) -> None:
        # An API key is not a session: nothing to tell the platform, and no
        # web session of ours to end — the browser's, if any, is not the key's.
        tokens = StoredTokens(access_token="k", refresh_token=None, expires_at=9e9, email=None, kind=KIND_API_KEY)
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] is None   # no refresh token → no Auth0 call
        assert calls["posted"] is None
        assert calls["cleared"] is True
        assert calls["opened"] is None

    def test_logged_out_already_just_clears(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, None)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["revoked"] is None
        assert calls["cleared"] is True
        assert calls["opened"] is None    # no session of ours to end in the browser

    def test_local_leaves_other_surfaces_alone(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout", "--local"])
        assert result.exit_code == 0
        assert calls["revoked"] == "rt"
        assert calls["cleared"] is True
        assert calls["posted"] is None
        assert calls["opened"] is None
        assert "/logout" not in result.output

    def test_platform_unreachable_still_logs_out_locally(self, monkeypatch) -> None:
        # A transport failure, not an HTTP answer: the platform is simply down.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_down=True)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] == "/auth/sign-out"
        assert calls["cleared"] is True
        assert calls["opened"] == self._web_logout()
        assert "Could not reach the platform" in result.output

    def test_already_signed_out_elsewhere_is_a_success(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_refuses="You signed out of ThoughtLeaders.")
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["cleared"] is True
        assert "Already signed out everywhere" in result.output
        assert "Could not reach" not in result.output

    def test_any_other_refusal_is_reported_in_the_platforms_words(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_refuses=("Nope.", "something_else"))
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["cleared"] is True
        assert "did not sign you out everywhere: Nope." in result.output

    def test_env_api_key_does_not_pretend_to_sign_out_everywhere(self, monkeypatch) -> None:
        # TL_API_KEY would be what reaches the platform, and an API key cannot
        # end a session — so say so instead of reporting a refusal as an outage.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        monkeypatch.setenv("TL_API_KEY", "ci-key")
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] is None
        assert calls["cleared"] is True
        assert "TL_API_KEY" in result.output

    def test_no_tty_prints_url_instead_of_opening_browser(self, monkeypatch) -> None:
        # An agent or script must never get a browser window popped at it.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, tty=False)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["opened"] is None
        assert self._web_logout() in result.output

    def test_browser_refusing_falls_back_to_url(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, browser_opens=False)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["opened"] == self._web_logout()
        assert self._web_logout() in result.output


class TestForgetSession:
    def _patch(self, monkeypatch, tokens):
        calls = {"revoked": None, "cleared": False}
        monkeypatch.setattr(auth_login, "load_tokens", lambda: tokens)
        monkeypatch.setattr(auth_login, "clear_tokens", lambda: calls.__setitem__("cleared", True))
        monkeypatch.setattr(auth_login, "revoke_refresh_token", lambda rt: calls.__setitem__("revoked", rt) or True)
        return calls

    def test_bearer_revokes_then_clears(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9))
        auth_login.forget_session(rejected_access_token="a")
        assert calls == {"revoked": "rt", "cleared": True}

    def test_the_same_session_refreshed_by_another_process_is_still_dropped(self, monkeypatch) -> None:
        # Another `tl` refreshed the store meanwhile: the access token differs,
        # the session — known by its sign-in time — is the one that was refused.
        calls = self._patch(
            monkeypatch, StoredTokens(access_token="rotated", refresh_token="rt2", expires_at=9e9, signed_in_at=1000.0)
        )
        auth_login.forget_session(rejected_access_token="old", rejected_signed_in_at=1000.0)
        assert calls == {"revoked": "rt2", "cleared": True}

    def test_a_newer_sign_in_is_kept_even_if_its_token_matches_nothing(self, monkeypatch) -> None:
        calls = self._patch(
            monkeypatch, StoredTokens(access_token="new", refresh_token="rt2", expires_at=9e9, signed_in_at=2000.0)
        )
        auth_login.forget_session(rejected_access_token="new", rejected_signed_in_at=1000.0)
        assert calls == {"revoked": None, "cleared": False}

    def test_api_key_is_kept(self, monkeypatch) -> None:
        # An API key is not a session and `tl auth login` cannot get it back.
        calls = self._patch(monkeypatch, StoredTokens(access_token="k", refresh_token=None, expires_at=9e9, kind=KIND_API_KEY))
        auth_login.forget_session(rejected_access_token="k")
        assert calls == {"revoked": None, "cleared": False}

    def test_a_newer_session_is_kept(self, monkeypatch) -> None:
        # The verdict was about a token a fresh sign-in has since replaced.
        calls = self._patch(monkeypatch, StoredTokens(access_token="new", refresh_token="rt2", expires_at=9e9))
        auth_login.forget_session(rejected_access_token="old")
        assert calls == {"revoked": None, "cleared": False}

    def test_nothing_stored_is_a_no_op(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, None)
        auth_login.forget_session(rejected_access_token="a")
        assert calls == {"revoked": None, "cleared": False}


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

    def test_quiet_expired_without_refresh_exits_2_silently(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token=None, expires_at=0.0, email="e@x.com")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        result = runner.invoke(auth_app, ["status", "-q"])
        assert result.exit_code == 2
        assert result.output == ""

    def test_expired_but_refreshable_counts_as_authenticated(self, monkeypatch) -> None:
        # The next command refreshes on its own; the pre-check hook must not
        # warn every hour that the user is "not authenticated".
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=0.0, email="e@x.com")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        assert runner.invoke(auth_app, ["status", "-q"]).exit_code == 0
        result = runner.invoke(auth_app, ["status"])
        assert result.exit_code == 0
        assert "e@x.com" in result.output

    def test_env_api_key_counts_as_authenticated(self, monkeypatch) -> None:
        monkeypatch.setenv("TL_API_KEY", "ci-key")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: None)
        assert runner.invoke(auth_app, ["status", "-q"]).exit_code == 0
        result = runner.invoke(auth_app, ["status"])
        assert result.exit_code == 0
        assert "TL_API_KEY" in result.output

    def test_verbose_still_reports(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        result = runner.invoke(auth_app, ["status"])
        assert result.exit_code == 0
        assert "e@x.com" in result.output


class TestLoginCommand:
    def test_method_skips_menu(self, monkeypatch) -> None:
        seen = {}
        monkeypatch.setattr(auth_commands, "_interactive", lambda: True)
        monkeypatch.setattr(auth_commands, "login_browser", lambda open_browser=True: seen.setdefault("open", open_browser))
        result = runner.invoke(auth_app, ["login", "--method", "browser", "--no-browser"])
        assert result.exit_code == 0
        assert seen["open"] is False   # --no-browser reached the flow
        assert "How would you like" not in result.output

    def test_browser_method_opens_a_window_only_at_a_terminal(self, monkeypatch) -> None:
        seen = {}
        monkeypatch.setattr(auth_commands, "login_browser", lambda open_browser=True: seen.setdefault("open", open_browser))
        monkeypatch.setattr(auth_commands, "_interactive", lambda: True)
        runner.invoke(auth_app, ["login", "--method", "browser"])
        assert seen.pop("open") is True
        monkeypatch.setattr(auth_commands, "_interactive", lambda: False)
        runner.invoke(auth_app, ["login", "--method", "browser"])
        assert seen.pop("open") is False   # an agent never gets a window popped at it

    def test_no_terminal_and_no_method_is_an_error(self, monkeypatch) -> None:
        # Piped stdin used to pick the default menu entry and open a browser.
        monkeypatch.setattr(auth_commands, "_interactive", lambda: False)
        monkeypatch.setattr(auth_commands, "login_browser", lambda open_browser=True: pytest.fail("must not log in"))
        result = runner.invoke(auth_app, ["login"], input="\n")
        assert result.exit_code == 2
        assert "--method" in result.output

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
        assert auth_login.web_logout_url(cfg) == "https://staging.example/logout?web_only=1"

    def test_default_auth0_domain_is_the_shared_custom_domain(self, monkeypatch) -> None:
        # One SSO cookie per host: only this host shares the web platform's session.
        monkeypatch.delenv("TL_AUTH0_DOMAIN", raising=False)
        assert auth_login.get_config().auth0_domain == "auth.thoughtleaders.io"


def _jwt(**claims) -> str:
    import base64  # noqa: PLC0415 — test helper
    import json  # noqa: PLC0415
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


class TestRefreshAccessToken:
    def _refresh(self, monkeypatch, old: StoredTokens) -> StoredTokens:
        class _Resp:
            status_code = 200
            def json(self):
                return {"access_token": _jwt(iat=5000), "expires_in": 3600}
        monkeypatch.setattr(auth_login.httpx, "post", lambda *a, **k: _Resp())
        saved = {}
        monkeypatch.setattr(auth_login, "save_tokens", lambda t: saved.setdefault("t", t))
        new = auth_login.refresh_access_token(old)
        assert saved["t"] is new
        return new

    def test_keeps_who_signed_in_and_when(self, monkeypatch) -> None:
        old = StoredTokens(access_token=_jwt(iat=4000), refresh_token="rt", expires_at=0.0, email="e@x.com", signed_in_at=123.0)
        new = self._refresh(monkeypatch, old)
        assert new.refresh_token == "rt"          # not rotated by this response
        assert new.email == "e@x.com"
        assert new.signed_in_at == 123.0           # the sign-in is older than the token

    def test_a_store_from_before_sign_in_times_gets_one_from_the_old_token(self, monkeypatch) -> None:
        # Otherwise such a session would carry no sign-in time forever and its
        # refreshed tokens would always look newer than any sign-out.
        old = StoredTokens(access_token=_jwt(iat=4000), refresh_token="rt", expires_at=0.0)
        assert self._refresh(monkeypatch, old).signed_in_at == 4000.0


class TestSignedInTime:
    def test_comes_from_the_tokens_own_clock(self) -> None:
        # The issuer's clock is what the platform compares against; a machine
        # running behind must not look like it signed in before its sign-out.
        assert auth_login.signed_in_time(_jwt(iat=1700000000)) == 1700000000.0

    def test_falls_back_to_the_local_clock_for_a_non_jwt(self, monkeypatch) -> None:
        monkeypatch.setattr(auth_login.time, "time", lambda: 42.0)
        assert auth_login.signed_in_time("opaque") == 42.0
        assert auth_login.signed_in_time(_jwt(iat=True)) == 42.0


class TestSignedOutMessage:
    def _run(self, raw) -> str:
        from rich.console import Console
        buf = Console(stderr=True, file=__import__("io").StringIO(), width=200)
        import tl_cli.client.errors as errors
        original = errors.err
        errors.err = buf
        try:
            with pytest.raises(SystemExit) as exc:
                handle_api_error(ApiError(401, raw.get("detail", ""), raw=raw))
        finally:
            errors.err = original
        assert exc.value.code == 2
        return buf.file.getvalue()

    def test_uses_the_servers_words(self) -> None:
        out = self._run({"detail": "You signed out of ThoughtLeaders.", "code": "signed_out"})
        assert "You signed out of ThoughtLeaders." in out
        assert "tl auth login" in out

    def test_keeps_a_hint_on_its_own_line(self) -> None:
        out = self._run({"detail": "You signed out. Try again.", "hint": "Try again.", "code": "signed_out"})
        assert "Hint:" in out and "Try again." in out

    def test_falls_back_when_the_server_sent_no_detail(self) -> None:
        out = self._run({"code": "signed_out"})
        assert "signed out" in out
        assert "{" not in out

    def test_server_text_is_not_markup(self) -> None:
        out = self._run({"detail": "Closed [/session] by admin", "code": "signed_out"})
        assert "Closed [/session] by admin" in out

    def test_other_401s_keep_the_generic_line(self) -> None:
        out = self._run({"detail": "Token has expired"})
        assert "Authentication required" in out
