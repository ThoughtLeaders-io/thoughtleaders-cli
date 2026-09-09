"""Authenticated HTTP client for the TL CLI API."""

import httpx

from tl_cli import __version__
from tl_cli.auth.login import forget_session, refresh_access_token
from tl_cli.auth.token_store import StoredTokens, load_tokens
from tl_cli.client.errors import SIGNED_OUT_CODE, ApiError
from tl_cli.config import get_config

# When the user signed in on this machine, as Unix seconds. A refreshed access
# token is newer than the sign-in it belongs to; this header lets the server
# judge the session by the sign-in, so a sign-out elsewhere still reaches a CLI
# whose access token has since been refreshed.
SIGNED_IN_AT_HEADER = "X-TL-Signed-In-At"


class TLClient:
    """HTTP client that handles auth injection, token refresh, and error mapping."""

    def __init__(self) -> None:
        self._config = get_config()
        self._client = httpx.Client(
            base_url=self._config.cli_api_base,
            timeout=30.0,
            headers={
                "User-Agent": f"tl-cli/{__version__}",
                "X-TL-Client": f"cli/{__version__}",
            },
        )

    def get(self, path: str, params: dict | None = None, timeout: float | None = None) -> dict:
        return self._request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, json_body: dict | None = None, timeout: float | None = None) -> dict:
        return self._request("POST", path, json_body=json_body, timeout=timeout)

    def patch(self, path: str, json_body: dict | None = None) -> dict:
        return self._request("PATCH", path, json_body=json_body)

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        headers = self._auth_headers()
        # Only overrides the client's default timeout when the caller asks
        # for one — passing `timeout=None` through to httpx means "no
        # timeout", not "use the default", so it's omitted entirely here.
        request_kwargs = {"params": params, "json": json_body, "headers": headers}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        response = self._client.request(method, path, **request_kwargs)

        # On a 401 for a stored session, try refreshing the token once — unless
        # the server says the user signed out (on the web, from the extension,
        # or elsewhere): then the session is over and a refresh would only
        # resurrect it. The verdict is read off the final response, so a
        # sign-out reported on the retry is honoured too. An API key is not a
        # session: never refresh or forget anything on its behalf.
        if response.status_code == 401 and "X-TL-Auth" not in headers:
            if self._error_code(response) != SIGNED_OUT_CODE:
                refreshed = self._refresh_and_get_headers()
                if refreshed:
                    headers = request_kwargs["headers"] = refreshed
                    response = self._client.request(method, path, **request_kwargs)
            if response.status_code == 401 and self._error_code(response) == SIGNED_OUT_CODE:
                signed_in_at = headers.get(SIGNED_IN_AT_HEADER)
                forget_session(
                    rejected_access_token=headers["Authorization"].removeprefix("Bearer "),
                    rejected_signed_in_at=float(signed_in_at) if signed_in_at else None,
                )

        if response.status_code >= 400:
            detail = self._extract_detail(response)
            try:
                raw = response.json() if response.text else None
            except Exception:
                raw = None
            raise ApiError(
                response.status_code, detail, raw=raw,
                url=str(response.url), response_text=response.text,
            )

        return response.json()

    def _auth_headers(self) -> dict[str, str]:
        """Get authorization headers from API key env var or stored credentials."""
        # API key env var takes priority (for CI/scripts)
        if self._config.api_key:
            return {
                "Authorization": f"Bearer {self._config.api_key}",
                "X-TL-Auth": "API-KEY",
            }

        tokens = load_tokens()
        if not tokens:
            raise ApiError(401, "Not authenticated. Run: tl auth login")

        if tokens.is_api_key:
            return {
                "Authorization": f"Bearer {tokens.access_token}",
                "X-TL-Auth": "API-KEY",
            }

        if tokens.is_expired and tokens.refresh_token:
            tokens = refresh_access_token(tokens)

        return self._bearer_headers(tokens)

    @staticmethod
    def _bearer_headers(tokens: StoredTokens) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
        if tokens.signed_in_at is not None:
            headers[SIGNED_IN_AT_HEADER] = str(int(tokens.signed_in_at))
        return headers

    def _refresh_and_get_headers(self) -> dict[str, str] | None:
        """Try to refresh the token. Returns new headers or None."""
        tokens = load_tokens()
        if not tokens or not tokens.refresh_token:
            return None
        try:
            return self._bearer_headers(refresh_access_token(tokens))
        except SystemExit:
            return None

    @staticmethod
    def _error_code(response: httpx.Response) -> str | None:
        """The machine-readable `code` of an error body, if there is one."""
        try:
            data = response.json()
        except Exception:
            return None
        code = data.get("code") if isinstance(data, dict) else None
        return code if isinstance(code, str) else None

    def _extract_detail(self, response: httpx.Response) -> str:
        """Extract error detail from response body."""
        try:
            data = response.json()
            return data.get("detail", data.get("error", str(data)))
        except Exception:
            text = response.text or ""
            if text.lstrip().startswith("<!") or text.lstrip().startswith("<html"):
                return f"HTTP {response.status_code} (non-JSON response from server)"
            return text or f"HTTP {response.status_code}"

    def close(self) -> None:
        self._client.close()


def get_client() -> TLClient:
    """Get a configured TL API client."""
    return TLClient()
