"""Constants shared across the AI gateway."""

from enum import StrEnum


class Provider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    MISTRAL = "mistral"


DEFAULT_GITGUARDIAN_API_URL = "https://api.gitguardian.com"

# Anthropic's Messages API requires an explicit max_tokens; OpenAI's does not.
ANTHROPIC_MAX_TOKENS = 1024

# Max characters per SSE fragment when flushing a buffered completion to the client.
SSE_FRAGMENT_MAX_LEN = 40

# Cheapest reasonable model per provider, used in README examples and manual
# testing so demo runs stay cheap.
DEMO_MODEL_OPENAI = f"{Provider.OPENAI}/gpt-4o-mini"
DEMO_MODEL_ANTHROPIC = f"{Provider.ANTHROPIC}/claude-haiku-4-5"
DEMO_MODEL_MISTRAL = f"{Provider.MISTRAL}/mistral-small-latest"

# Synthetic location reported alongside incidents created from this demo gateway.
INCIDENT_LOCATION_PREFIX = "https://ai-gateway.local/v1/chat/completions"
