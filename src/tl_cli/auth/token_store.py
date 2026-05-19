"""Secure token storage using OS keychain (keyring) with file fallback."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

import keyring
from keyring.errors import NoKeyringError

from tl_cli.config import ensure_config_dir

SERVICE_NAME = "tl-cli"
FALLBACK_FILE = "credentials.json"


KIND_BEARER = "bearer"
KIND_API_KEY = "api_key"


@dataclass
class StoredTokens:
    """Auth credentials stored in the keychain.

    `kind` distinguishes the OAuth2/Auth0 access-token flow ("bearer") from
    a long-lived API key flow ("api_key"). API keys don't expire client-side
    and have no refresh token — `refresh_token` and `expires_at` stay unset
    in that case.
    """

    access_token: str
    refresh_token: str | None
    expires_at: float  # Unix timestamp; 0 for API keys
    email: str | None = None
    kind: str = KIND_BEARER

    @property
    def is_expired(self) -> bool:
        if self.kind == KIND_API_KEY:
            return False
        # 5-minute buffer before actual expiry
        return time.time() > (self.expires_at - 300)

    @property
    def is_api_key(self) -> bool:
        return self.kind == KIND_API_KEY

    def to_json(self) -> str:
        return json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "email": self.email,
            "kind": self.kind,
        })

    @classmethod
    def from_json(cls, data: str) -> "StoredTokens":
        parsed = json.loads(data)
        return cls(
            access_token=parsed["access_token"],
            refresh_token=parsed.get("refresh_token"),
            expires_at=parsed.get("expires_at") or 0,
            email=parsed.get("email"),
            kind=parsed.get("kind", KIND_BEARER),
        )


def save_tokens(tokens: StoredTokens) -> None:
    """Save tokens to the OS keychain, falling back to encrypted file."""
    data = tokens.to_json()
    try:
        keyring.set_password(SERVICE_NAME, "tokens", data)
    except (NoKeyringError, Exception):
        _save_to_file(data)


def load_tokens() -> StoredTokens | None:
    """Load tokens from the OS keychain or fallback file."""
    try:
        data = keyring.get_password(SERVICE_NAME, "tokens")
        if data:
            return StoredTokens.from_json(data)
    except (NoKeyringError, Exception):
        pass

    return _load_from_file()


def clear_tokens() -> None:
    """Remove stored tokens from keychain and fallback file."""
    try:
        keyring.delete_password(SERVICE_NAME, "tokens")
    except (NoKeyringError, Exception):
        pass

    fallback = ensure_config_dir() / FALLBACK_FILE
    if fallback.exists():
        fallback.unlink()


def _save_to_file(data: str) -> None:
    """Fallback: save to config dir (less secure than keychain)."""
    path = ensure_config_dir() / FALLBACK_FILE
    path.write_text(data)
    path.chmod(0o600)


def _load_from_file() -> StoredTokens | None:
    """Fallback: load from config dir."""
    path = ensure_config_dir() / FALLBACK_FILE
    if not path.exists():
        return None
    try:
        return StoredTokens.from_json(path.read_text())
    except (json.JSONDecodeError, KeyError):
        return None
