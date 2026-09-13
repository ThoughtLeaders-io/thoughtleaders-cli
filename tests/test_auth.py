"""Tests for PKCE and token storage."""

import io
import webbrowser

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

import tl_cli.client.errors as errors_module
from tl_cli.auth import commands as auth_commands
from tl_cli.auth import login as auth_login
from tl_cli.auth.commands import app as auth_app
from tl_cli.auth.login import revoke_refresh_token
from tl_cli.auth.pkce import generate_pkce_pair
from tl_cli.auth.token_store import KIND_API_KEY, KIND_BEARER, StoredTokens
from tl_cli.client.errors import ApiError, handle_api_error

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_developer_env(monkeypatch):
    """Run against the CLI's own defaults, never the developer's shell.

    `TL_API_KEY` and `TL_API_URL` are exported in day-to-day development and
    are read by `tl auth status` and the HTTP client, so a test that does not
    set them itself must not inherit them.
    """
    monkeypatch.delenv("TL_API_KEY", raising=False)
    monkeypatch.delenv("TL_API_URL", raising=False)


def _flat(output: str) -> str:
    """Console output as one line — the console wraps at its width, so a long
    message cannot be matched as a single literal."""
    return " ".join(output.split())


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

    def test_a_record_holding_a_field_this_version_dropped_still_loads(self):
        # Older CLI versions wrote an extra bookkeeping field alongside the
        # credentials. Such a store must keep working after an upgrade rather
        # than forcing the user to log in again.
        legacy = (
            '{"access_token": "x", "refresh_token": "y", "expires_at": 1.0, '
            '"email": "e", "kind": "bearer", "some_retired_field": 1700000000.0}'
        )
        restored = StoredTokens.from_json(legacy)
        assert restored.access_token == "x"
        assert restored.refresh_token == "y"
        assert restored.email == "e"
        assert restored.kind == KIND_BEARER

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
        self.calls["posted"].append(path)
        self.calls["order"].append("signed out")
        if self.fail == "refresh":
            raise SystemExit(2)  # what a refresh that Auth0 refused raises
        if self.fail:
            raise httpx.ConnectError("offline")
        if self.refuse:
            detail, code = self.refuse if isinstance(self.refuse, tuple) else (self.refuse, "signed_out")
            raise ApiError(401, detail, raw={"detail": detail, "code": code})
        return {"signed_out_at": "2026-09-09T00:00:00Z"}

    def close(self):
        pass


OFFLINE_MESSAGE = (
    "Could not reach ThoughtLeaders to sign out everywhere. This machine's credentials are cleared, "
    "but your other sessions stay signed in; sign out on the web platform once you are online to end them."
)
REFUSED_MESSAGE = "Your other sessions stay signed in; sign out on the web platform to end them."


class TestLogoutCommand:
    def _patch(self, monkeypatch, tokens, *, api_down=False, api_refuses=None):
        calls = {"revoked": None, "cleared": False, "posted": [], "order": [], "stored_only": None}

        def clear():
            calls["cleared"] = True
            calls["order"].append("cleared")

        def revoke(refresh_token):
            calls["revoked"] = refresh_token
            calls["order"].append("revoked")
            return True

        def client(stored_session_only=False):
            calls["stored_only"] = stored_session_only
            return _FakeClient(calls, fail=api_down, refuse=api_refuses)

        def no_browser(*args, **kwargs):
            pytest.fail("logout must never open a browser")

        monkeypatch.setattr(auth_commands, "load_tokens", lambda: tokens)
        monkeypatch.setattr(auth_commands, "clear_tokens", clear)
        monkeypatch.setattr(auth_commands, "revoke_refresh_token", revoke)
        monkeypatch.setattr(auth_commands, "get_client", client)
        # Nothing about logout may pop a window — not at a terminal either.
        monkeypatch.setattr(webbrowser, "open", no_browser)
        return calls

    def test_bearer_logout_signs_out_everywhere_then_revokes_then_clears(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        # Told once, and told about the stored session rather than TL_API_KEY.
        assert calls["posted"] == ["/auth/sign-out"]
        assert calls["stored_only"] is True
        assert calls["revoked"] == "rt"
        assert calls["cleared"] is True
        assert calls["order"] == ["signed out", "revoked", "cleared"]
        assert "Signed out everywhere." in _flat(result.output)
        assert "Logged out successfully." in _flat(result.output)
        assert OFFLINE_MESSAGE not in _flat(result.output)

    def test_api_key_logout_only_clears_the_key(self, monkeypatch) -> None:
        # An API key is not a session: there is nothing to end anywhere else.
        tokens = StoredTokens(access_token="k", refresh_token=None, expires_at=9e9, email=None, kind=KIND_API_KEY)
        calls = self._patch(monkeypatch, tokens)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] == []      # the platform is never told
        assert calls["revoked"] is None   # no refresh token → no Auth0 call
        assert calls["cleared"] is True
        assert "API key is not a session" in _flat(result.output)

    def test_env_api_key_alone_is_not_a_session_either(self, monkeypatch) -> None:
        # TL_API_KEY with nothing stored: nothing to sign out of, and the key is
        # not ours to remove — say so instead of claiming a logout happened.
        calls = self._patch(monkeypatch, None)
        monkeypatch.setenv("TL_API_KEY", "ci-key")
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] == []
        assert "TL_API_KEY is set in your environment" in _flat(result.output)
        assert "stays in effect" in _flat(result.output)
        assert "Logged out successfully." not in _flat(result.output)

    def test_logged_out_already_just_clears(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, None)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] == []
        assert calls["revoked"] is None
        assert calls["cleared"] is True

    def test_platform_unreachable_still_clears_and_says_to_try_again(self, monkeypatch) -> None:
        # A transport failure: the sign-out was not recorded anywhere, so the
        # user has to be told their other sessions are still open.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_down=True)
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] == ["/auth/sign-out"]
        assert calls["cleared"] is True
        assert OFFLINE_MESSAGE in _flat(result.output)

    def test_a_refresh_giving_up_mid_logout_still_logs_out_locally(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_down="refresh")
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["cleared"] is True
        assert OFFLINE_MESSAGE in _flat(result.output)

    def test_revokes_the_refresh_token_the_store_holds_after_the_platform_call(self, monkeypatch) -> None:
        # The sign-out call may have refreshed (rotating the refresh token).
        first = StoredTokens(access_token="a", refresh_token="rt-old", expires_at=9e9, email="e@x.com")
        rotated = StoredTokens(access_token="b", refresh_token="rt-new", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, first)
        loads = iter([first, rotated])
        monkeypatch.setattr(auth_commands, "load_tokens", lambda: next(loads))
        runner.invoke(auth_app, ["logout"])
        assert calls["revoked"] == "rt-new"

    def test_already_signed_out_elsewhere_is_a_success(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_refuses="You signed out of ThoughtLeaders.")
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["cleared"] is True
        assert "Already signed out everywhere" in _flat(result.output)
        assert OFFLINE_MESSAGE not in _flat(result.output)
        assert REFUSED_MESSAGE not in _flat(result.output)

    def test_any_other_refusal_is_reported_in_the_platforms_words(self, monkeypatch) -> None:
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens, api_refuses=("Nope.", "something_else"))
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["cleared"] is True
        assert "did not sign you out everywhere: Nope." in _flat(result.output)
        # ThoughtLeaders answered, so it was reached: no offline wording.
        assert OFFLINE_MESSAGE not in _flat(result.output)
        assert REFUSED_MESSAGE in _flat(result.output)

    def test_env_api_key_does_not_get_in_the_way_of_a_stored_session(self, monkeypatch) -> None:
        # TL_API_KEY is not the session being ended: the stored session is.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        monkeypatch.setenv("TL_API_KEY", "ci-key")
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert calls["posted"] == ["/auth/sign-out"]
        assert calls["stored_only"] is True
        assert calls["cleared"] is True


    def test_an_answer_without_a_body_is_still_a_success(self, monkeypatch) -> None:
        # The real client returns {} for a bodiless 2xx; logout must read that
        # as "told", not as a failure.
        tokens = StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9, email="e@x.com")
        calls = self._patch(monkeypatch, tokens)
        monkeypatch.setattr(_FakeClient, "post", lambda self, path, json_body=None: (calls["posted"].append(path), {})[1])
        result = runner.invoke(auth_app, ["logout"])
        assert result.exit_code == 0
        assert "Signed out everywhere." in _flat(result.output)
        assert OFFLINE_MESSAGE not in _flat(result.output)


class TestLoginHelpers:
    def test_a_busy_callback_port_is_a_clear_error_not_a_traceback(self, monkeypatch) -> None:
        def busy(*args, **kwargs):
            raise OSError(98, "Address already in use")

        monkeypatch.setattr(auth_login, "_start_callback_server", busy)
        buf = io.StringIO()
        monkeypatch.setattr(auth_login, "console", Console(file=buf, force_terminal=False, width=200))
        with pytest.raises(SystemExit) as exc:
            auth_login.login_browser()
        assert exc.value.code == 1
        assert "Could not listen on port" in buf.getvalue()
        assert "--method device" in buf.getvalue()

    def test_open_in_browser_swallows_a_missing_browser(self, monkeypatch) -> None:
        def boom(url):
            raise RuntimeError("no browser here")

        monkeypatch.setattr(webbrowser, "open", boom)
        assert auth_login.open_in_browser("https://example.test") is False

    def test_the_callback_page_escapes_what_the_redirect_says(self) -> None:
        # error_description arrives from the redirect; it is text, not markup.
        result = auth_login._CallbackResult()
        server, port = auth_login._start_callback_server(result, "state-1")
        try:
            resp = httpx.get(
                f"http://127.0.0.1:{port}/callback",
                params={"state": "state-1", "error": "access_denied", "error_description": "<img src=x onerror=alert(1)>"},
            )
        finally:
            server.shutdown()
            server.server_close()
        assert "<img" not in resp.text
        assert "&lt;img" in resp.text
        assert result.error == "access_denied"


class TestApiKeyLogin:
    def _patch(self, monkeypatch, key: str, whoami):
        saved = []
        monkeypatch.setattr(auth_commands, "_read_masked", lambda prompt: key)
        monkeypatch.setattr(auth_commands, "save_tokens", lambda tokens: saved.append(tokens))
        monkeypatch.setattr(auth_commands, "clear_tokens", lambda: saved.append(None))

        class Client:
            def get(self, path):
                if isinstance(whoami, Exception):
                    raise whoami
                return whoami

            def close(self):
                pass

        monkeypatch.setattr(auth_commands, "get_client", lambda stored_session_only=False: Client())
        return saved

    def test_a_valid_key_is_stored_with_its_owners_email(self, monkeypatch) -> None:
        saved = self._patch(monkeypatch, "k-123", {"user": {"email": "owner@x.com"}})
        result = runner.invoke(auth_app, ["login", "--method", "api-key"])
        assert result.exit_code == 0
        assert saved[-1].kind == KIND_API_KEY
        assert saved[-1].access_token == "k-123"
        assert saved[-1].email == "owner@x.com"
        assert "Authenticated as: owner@x.com" in _flat(result.output)

    def test_a_rejected_key_is_not_kept(self, monkeypatch) -> None:
        saved = self._patch(monkeypatch, "bad", ApiError(401, "Invalid API key"))
        result = runner.invoke(auth_app, ["login", "--method", "api-key"])
        assert result.exit_code == 1
        assert saved[-1] is None  # cleared after the failed probe
        assert "API key rejected" in _flat(result.output)


class TestForgetSession:
    def _patch(self, monkeypatch, tokens):
        calls = {"revoked": None, "cleared": False}
        monkeypatch.setattr(auth_login, "load_tokens", lambda: tokens)
        monkeypatch.setattr(auth_login, "clear_tokens", lambda: calls.__setitem__("cleared", True))
        monkeypatch.setattr(auth_login, "revoke_refresh_token", lambda rt: calls.__setitem__("revoked", rt) or True)
        return calls

    def test_bearer_revokes_then_clears(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, StoredTokens(access_token="a", refresh_token="rt", expires_at=9e9))
        auth_login.forget_session("a")
        assert calls == {"revoked": "rt", "cleared": True}

    def test_api_key_is_kept(self, monkeypatch) -> None:
        # An API key is not a session and `tl auth login` cannot get it back.
        calls = self._patch(monkeypatch, StoredTokens(access_token="k", refresh_token=None, expires_at=9e9, kind=KIND_API_KEY))
        auth_login.forget_session("k")
        assert calls == {"revoked": None, "cleared": False}

    def test_a_token_the_store_no_longer_holds_leaves_it_alone(self, monkeypatch) -> None:
        # A fresh sign-in, or a refresh another `tl` process did, has replaced
        # the credential that was refused; that one has not been refused.
        calls = self._patch(monkeypatch, StoredTokens(access_token="new", refresh_token="rt2", expires_at=9e9))
        auth_login.forget_session("old")
        assert calls == {"revoked": None, "cleared": False}

    def test_nothing_stored_is_a_no_op(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, None)
        auth_login.forget_session("a")
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
            server.server_close()
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
            server.server_close()
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
            server.server_close()
        assert r.status_code == 200
        assert result.code is None
        assert result.error


class TestWebUrls:
    def test_signin_url_derives_from_api_url(self, monkeypatch) -> None:
        monkeypatch.setenv("TL_API_URL", "https://staging.example/")
        cfg = auth_login.get_config()
        assert auth_login.web_signin_url(cfg) == "https://staging.example/signin?go=1&from=cli"

    def test_default_auth0_domain_is_the_shared_custom_domain(self, monkeypatch) -> None:
        # One SSO cookie per host: only this host shares the web platform's session.
        monkeypatch.delenv("TL_AUTH0_DOMAIN", raising=False)
        assert auth_login.get_config().auth0_domain == "auth.thoughtleaders.io"


class TestRefreshAccessToken:
    def _refresh(self, monkeypatch, old: StoredTokens) -> StoredTokens:
        class _Resp:
            status_code = 200

            def json(self):
                return {"access_token": "new-jwt", "expires_in": 3600}

        monkeypatch.setattr(auth_login.httpx, "post", lambda *a, **k: _Resp())
        saved = {}
        monkeypatch.setattr(auth_login, "save_tokens", lambda t: saved.setdefault("t", t))
        new = auth_login.refresh_access_token(old)
        assert saved["t"] is new
        return new

    def test_keeps_who_signed_in(self, monkeypatch) -> None:
        old = StoredTokens(access_token="old-jwt", refresh_token="rt", expires_at=0.0, email="e@x.com")
        new = self._refresh(monkeypatch, old)
        assert new.access_token == "new-jwt"
        assert new.refresh_token == "rt"          # not rotated by this response
        assert new.email == "e@x.com"             # `tl auth status` still names the user
        assert not new.is_expired


class TestSignedOutMessage:
    def _run(self, raw, monkeypatch) -> str:
        buf = Console(stderr=True, file=io.StringIO(), width=200)
        monkeypatch.setattr(errors_module, "err", buf)
        with pytest.raises(SystemExit) as exc:
            handle_api_error(ApiError(401, raw.get("detail", ""), raw=raw))
        assert exc.value.code == 2
        return buf.file.getvalue()

    def test_uses_the_servers_words(self, monkeypatch) -> None:
        out = self._run({"detail": "You signed out of ThoughtLeaders.", "code": "signed_out"}, monkeypatch)
        assert "You signed out of ThoughtLeaders." in out
        assert "tl auth login" in out

    def test_keeps_a_hint_on_its_own_line(self, monkeypatch) -> None:
        out = self._run({"detail": "You signed out. Try again.", "hint": "Try again.", "code": "signed_out"}, monkeypatch)
        assert "Hint:" in out and "Try again." in out

    def test_falls_back_when_the_server_sent_no_detail(self, monkeypatch) -> None:
        out = self._run({"code": "signed_out"}, monkeypatch)
        assert "signed out" in out
        assert "{" not in out

    def test_server_text_is_not_markup(self, monkeypatch) -> None:
        out = self._run({"detail": "Closed [/session] by admin", "code": "signed_out"}, monkeypatch)
        assert "Closed [/session] by admin" in out

    def test_a_hint_is_not_markup_either(self, monkeypatch) -> None:
        out = self._run({"detail": "You signed out.", "hint": "Ask [/admin] for help", "code": "signed_out"}, monkeypatch)
        assert "Ask [/admin] for help" in out

    def test_other_401s_keep_the_generic_line(self, monkeypatch) -> None:
        out = self._run({"detail": "Token has expired"}, monkeypatch)
        assert "Authentication required" in out
