"""Constants shared across the webhook receiver and the backfill command."""

DEFAULT_GITGUARDIAN_API_URL = "https://api.gitguardian.com"
DEFAULT_GITHUB_API_URL = "https://api.github.com"

# /v1/scan/create-incidents takes at most 20 documents and a 1MB body per call; the
# byte budget leaves headroom for the JSON envelope around the documents' content.
MAX_DOCUMENTS_PER_SCAN = 20
MAX_BATCH_BYTES = 900_000

GITHUB_PAGE_SIZE = 100

HTTP_TIMEOUT_SECONDS = 20
HTTP_MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 1
BACKOFF_MAX_SECONDS = 60
# GitHub asks to wait at least a minute after a secondary rate limit without Retry-After.
GITHUB_SECONDARY_RATE_LIMIT_WAIT_SECONDS = 60

USER_AGENT = "gitguardian-github-issues-prs-demo"

RETRY_AFTER_HEADER = "retry-after"
GITHUB_RATELIMIT_REMAINING_HEADER = "x-ratelimit-remaining"
GITHUB_RATELIMIT_RESET_HEADER = "x-ratelimit-reset"
