"""Configuration management for the TL CLI."""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default API base URL
DEFAULT_API_URL = "https://app.thoughtleaders.io"

# Auth0 defaults (CLI-specific application)
DEFAULT_AUTH0_DOMAIN = "dev-mq73b7zhdhwvgae1.us.auth0.com"
DEFAULT_AUTH0_CLIENT_ID = "BWTaMBWRP0wxWjPXbSa9FHhbz7RKfURu" # Set when Auth0 app is created, not secret
DEFAULT_AUTH0_AUDIENCE = "https://app.thoughtleaders.io/mcp" # No relation to the MCP API, just uses the same OAuth0 "audience" config
DEFAULT_AUTH0_CALLBACK_PORT = 8484  # Fixed port — must match Auth0 allowed callback URLs

# Config directory
CONFIG_DIR = Path.home() / ".config" / "tl"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    """Runtime configuration resolved from env vars, config file, and defaults."""

    api_url: str = field(default_factory=lambda: os.environ.get("TL_API_URL", DEFAULT_API_URL))
    api_key: str | None = field(default_factory=lambda: os.environ.get("TL_API_KEY"))
    auth0_domain: str = field(
        default_factory=lambda: os.environ.get("TL_AUTH0_DOMAIN", DEFAULT_AUTH0_DOMAIN)
    )
    auth0_client_id: str = field(
        default_factory=lambda: os.environ.get("TL_AUTH0_CLIENT_ID", DEFAULT_AUTH0_CLIENT_ID)
    )
    auth0_audience: str = field(
        default_factory=lambda: os.environ.get("TL_AUTH0_AUDIENCE", DEFAULT_AUTH0_AUDIENCE)
    )

    @property
    def cli_api_base(self) -> str:
        return f"{self.api_url.rstrip('/')}/api/cli/v1"

    def app_url(self, path: str) -> str:
        """Build a TL web-app URL (not the CLI API) from a relative path.

        Same host as ``api_url``, used for user-facing deep links into the web
        app (e.g. a channel's analysis page). These pages live at the site
        root, not under ``/api/cli/v1``, so they don't go through
        ``cli_api_base``. Honoring ``TL_API_URL`` keeps links pointing at
        whichever environment the CLI is talking to.
        """
        return f"{self.api_url.rstrip('/')}/{path.lstrip('/')}"


# Global flags, set by options on the root command
debug: bool = False


def get_config() -> Config:
    """Get the current configuration."""
    return Config()


def ensure_config_dir() -> Path:
    """Ensure the config directory exists and return it."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR
