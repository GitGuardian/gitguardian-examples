# GitGuardian Secret Scanning of GitHub Issues and Pull Requests

GitGuardian's GitHub integration scans code, not the conversations around it. This example scans GitHub issues, pull requests, comments and reviews with GitGuardian and raises the secrets it finds as incidents on a [custom source](https://docs.gitguardian.com/platform/configure-integrations/custom-sources).

- **`webhook`** (`app/main.py`): a [FastAPI](https://fastapi.tiangolo.com/) endpoint for GitHub webhooks that scans content as soon as it is created or edited.
- **`backfill`** (`app/backfill.py`): a command that scans what a repository already has.

Both send content to [`/v1/scan/create-incidents`](https://api.gitguardian.com/docs#tag/Scan-Methods/operation/scan_create_incidents), which scans it and raises an incident for every secret in one call. Each occurrence links back to the exact issue, pull request, comment or review. Request and response bodies, GitHub's included, are parsed with pydantic models.

| GitHub content | Webhook event (actions) |
| --- | --- |
| Issue title and description | `issues` (`opened`, `edited`) |
| Pull request title and description | `pull_request` (`opened`, `edited`) |
| Issue and pull request conversation comments | `issue_comment` (`created`, `edited`) |
| Pull request review bodies | `pull_request_review` (`submitted`, `edited`) |
| Pull request inline review comments | `pull_request_review_comment` (`created`, `edited`) |

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and a GitGuardian personal access token with the `scan:create-incidents` scope, from https://dashboard.gitguardian.com/api/personal-access-tokens.

1. In GitGuardian, create a custom source (Integrations > Custom source) and copy its UUID. Issues and pull requests share one source; name it after where the content lives, e.g. `github.com/<org> Issues & PRs`.
2. Install and configure:

```bash
uv sync
cp .env.example .env
```

Edit `.env`: set `GITGUARDIAN_API_KEY`, `GITGUARDIAN_SOURCE_UUID`, and `GITHUB_WEBHOOK_SECRET` and/or `GITHUB_TOKEN` depending on what you run. All env vars are validated in `app/config.py`.

## Webhook receiver

```bash
uv run --env-file .env webhook
```

It checks the configuration and GitGuardian API access before listening, and exits with a single `Startup failed` log line if either is wrong. Pass `--host` and `--port` to change where it listens (default `127.0.0.1:8000`).

GitHub needs a public URL to deliver to. Locally, the [`gh webhook`](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/using-the-github-cli-to-forward-webhooks-for-testing) extension forwards a repository's events through a temporary webhook, removed when you stop it. It needs admin access to the repository:

```bash
gh extension install cli/gh-webhook
gh webhook forward --repo=<owner>/<repo> \
  --events=issues,issue_comment,pull_request,pull_request_review,pull_request_review_comment \
  --url=http://localhost:8000/webhook --secret="$(grep '^GITHUB_WEBHOOK_SECRET=' .env | cut -d= -f2-)"
```

Don't `source .env` in that shell: `gh` would pick up the read-only `GITHUB_TOKEN` instead of your own login and fail to create the webhook.

In production, add an organization or repository webhook pointing at `https://<your-host>/webhook`, with content type `application/json`, the same secret, and the five events above.

Try it by commenting on an issue with GitGuardian's test token, which is always detected:

```bash
gh issue comment <number> --repo <owner>/<repo> --body "token: ggtt-v-12345azert"
```

The server logs a `Secret detected` line and a GitGuardian incident appears on the custom source, linking to the comment. The webhook response (visible in the webhook's "Recent Deliveries" on GitHub) is `{"status": "secret_detected", "findings": [...]}`, `{"status": "clean"}`, or `{"status": "ignored"}` for events that aren't scanned. Deliveries with an invalid signature get a `401`. If GitGuardian can't be reached the delivery fails with a `502` so it can be redelivered from GitHub.

## Backfill

```bash
uv run --env-file .env backfill <owner>/<repo>
```

`GITHUB_TOKEN` needs read access to the repository's issues and pull requests. Pass `--since 2026-01-01T00:00:00Z` to only scan content updated after a date. The command exits with `1` if it found any secret, and `2` if a setting is missing or GitHub or GitGuardian returned an error. A fine-grained token limited to public repositories gets a `404` on private ones. Reviews are fetched per pull request, so backfilling a repository with many pull requests takes one extra GitHub API call for each; GitHub allows 5,000 per hour per user.

## Lint and type-check

```bash
uv run ruff check .
uv run ruff format .
uv run ty check .
```

## Notes

- Both GitHub and GitGuardian calls retry rate-limited (`429`, GitHub's rate-limit `403`), `5xx` and network failures, up to 5 attempts (`app/retry.py`). They wait for `Retry-After` or GitHub's rate-limit reset when given, and back off exponentially otherwise.
- Log messages are constant; the details (repository, URL, counts, timings) are attached as JSON attributes, e.g. `INFO github_backfill: Backfill finished {"repo": ..., "duration_seconds": 10.7, "documents": 66, "secrets": 0}` (`app/logs.py`).
- GitGuardian keeps one occurrence per secret and document `filename`, so rerunning the backfill, redelivering a webhook or rescanning an edited comment doesn't add duplicate occurrences.
- `/scan/create-incidents` is in beta. Each document's `filename` identifies the GitHub object it came from, e.g. `<owner>/<repo>/issues/comments/<id>`.
- The scan only sees the latest version of an edited comment. The secret stays in GitHub's edit history, so rotate it rather than just editing it out.
- GitHub Enterprise Server works by setting `GITHUB_API_URL` for the backfill; the webhook receiver is host-agnostic.
