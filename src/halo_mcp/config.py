"""Configuration contract for the Halo MCP server.

All settings come from the environment (a git-ignored ``.env`` file or real
environment variables) with the ``HALO_`` prefix. Nothing is hardcoded; the
client secret is held as a :class:`~pydantic.SecretStr` so it never leaks into
logs, reprs, or tracebacks.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Least-privilege default: read-only across the entities the read tools touch.
# Only scope names that exist on Halo — there is no read:users or read:agents
# scope (requesting either yields invalid_scope at the token endpoint). Agent,
# team, status and user/contact lookups need no dedicated scope.
DEFAULT_READ_SCOPES = "read:tickets read:assets read:customers"


class Settings(BaseSettings):
    """Environment-driven configuration.

    Field ``api_url`` maps to env var ``HALO_API_URL``, and so on.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HALO_",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Required ---
    api_url: str = Field(description="Resource Server API base (see .env.example / README).")
    auth_url: str = Field(description="Full OAuth token endpoint URL.")
    client_id: str = Field(description="Registered API application client id.")
    client_secret: SecretStr = Field(description="Registered API application client secret.")

    # --- Optional ---
    tenant: str | None = Field(
        default=None,
        description="Tenant name; appended as ?tenant= when the auth server requires it.",
    )
    scopes: str = Field(
        default=DEFAULT_READ_SCOPES,
        description="Space-separated OAuth scopes (least-privilege read set by default).",
    )
    enable_writes: bool = Field(
        default=False,
        description="Register write tools. Must be explicitly true to enable.",
    )
    page_size: int = Field(default=50, ge=1, le=1000, description="Default list page size.")
    timeout: float = Field(default=30.0, gt=0, description="httpx request timeout in seconds.")
    long_timeout: float = Field(
        default=120.0,
        gt=0,
        description="httpx timeout (seconds) for heavy endpoints such as reports.",
    )

    @property
    def base_url(self) -> str:
        """API base with any trailing slash removed, for clean path joining."""
        return self.api_url.rstrip("/")


def load_settings() -> Settings:
    """Load settings from the environment (.env / OS env).

    Wrapped so the single unavoidable type-ignore (pydantic populates these
    required fields at runtime, but the static type-checker cannot know that)
    lives in exactly one place.
    """
    return Settings()  # type: ignore[call-arg]
