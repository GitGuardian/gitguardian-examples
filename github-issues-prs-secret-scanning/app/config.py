import os
from dataclasses import dataclass

from app.constants import DEFAULT_GITGUARDIAN_API_URL, DEFAULT_GITHUB_API_URL


@dataclass(frozen=True)
class GitGuardianSettings:
    api_key: str
    api_url: str
    source_uuid: str


@dataclass(frozen=True)
class WebhookSettings:
    gitguardian: GitGuardianSettings
    github_webhook_secret: str
    # Optional: without it, incidents don't carry the author's email.
    github_token: str | None
    github_api_url: str


@dataclass(frozen=True)
class BackfillSettings:
    gitguardian: GitGuardianSettings
    github_token: str
    github_api_url: str


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def _require(name: str, hint: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"{name} is not set. {hint}")
    return value


def _load_gitguardian_settings() -> GitGuardianSettings:
    return GitGuardianSettings(
        api_key=_require(
            "GITGUARDIAN_API_KEY",
            "Create a personal access token with the scan:create-incidents scope in the "
            "GitGuardian dashboard, under API > Personal access tokens.",
        ),
        api_url=os.environ.get("GITGUARDIAN_API_URL", DEFAULT_GITGUARDIAN_API_URL),
        source_uuid=_require(
            "GITGUARDIAN_SOURCE_UUID",
            "Create a custom source (Integrations > Custom source) and use its UUID.",
        ),
    )


def load_webhook_settings() -> WebhookSettings:
    """Parse and validate every environment variable the webhook receiver reads."""
    return WebhookSettings(
        gitguardian=_load_gitguardian_settings(),
        github_webhook_secret=_require(
            "GITHUB_WEBHOOK_SECRET",
            "Use the same value as the secret configured on the GitHub webhook.",
        ),
        github_token=os.environ.get("GITHUB_TOKEN") or None,
        github_api_url=os.environ.get("GITHUB_API_URL", DEFAULT_GITHUB_API_URL),
    )


def load_backfill_settings() -> BackfillSettings:
    """Parse and validate every environment variable the backfill command reads."""
    return BackfillSettings(
        gitguardian=_load_gitguardian_settings(),
        github_token=_require(
            "GITHUB_TOKEN",
            "Use a token with read access to the repository's issues and pull requests.",
        ),
        github_api_url=os.environ.get("GITHUB_API_URL", DEFAULT_GITHUB_API_URL),
    )
