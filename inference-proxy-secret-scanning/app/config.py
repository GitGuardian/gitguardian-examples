import os
from dataclasses import dataclass

from app.constants import DEFAULT_GITGUARDIAN_API_URL


@dataclass(frozen=True)
class Settings:
    gitguardian_api_key: str
    base_url: str
    gitguardian_source_uuid: str | None
    openai_api_key: str | None
    anthropic_api_key: str | None
    mistral_api_key: str | None


def load_settings() -> Settings:
    """Parse and validate every environment variable this app reads, in one place."""
    gitguardian_api_key = os.environ.get("GITGUARDIAN_API_KEY")
    if not gitguardian_api_key:
        raise RuntimeError(
            "GITGUARDIAN_API_KEY is not set. Create a personal access token "
            "(scope: scan) at https://dashboard.gitguardian.com/api/personal-access-tokens "
            "and export it before starting the proxy."
        )

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    mistral_api_key = os.environ.get("MISTRAL_API_KEY")
    if not any((openai_api_key, anthropic_api_key, mistral_api_key)):
        raise RuntimeError(
            "At least one of OPENAI_API_KEY, ANTHROPIC_API_KEY, or MISTRAL_API_KEY must be set."
        )

    return Settings(
        gitguardian_api_key=gitguardian_api_key,
        base_url=os.environ.get("GITGUARDIAN_INSTANCE", DEFAULT_GITGUARDIAN_API_URL),
        gitguardian_source_uuid=os.environ.get("GITGUARDIAN_SOURCE_UUID"),
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        mistral_api_key=mistral_api_key,
    )
