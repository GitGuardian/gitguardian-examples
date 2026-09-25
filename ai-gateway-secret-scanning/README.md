# GitGuardian Secret Scanning in an AI Gateway

A minimal [FastAPI](https://fastapi.tiangolo.com/) AI gateway in front of OpenAI, Anthropic, and Mistral that scans every prompt and every completion with GitGuardian and blocks the call (fail-closed) if a secret is found.

- Prompts are scanned before being forwarded upstream; completions are scanned before being returned to the caller.
- Scanning hits GitGuardian's [`/v1/multiscan`](https://api.gitguardian.com/docs#tag/Scan-Methods/operation/multiple_scan) directly over HTTP (`httpx` + `pydantic`, no `pygitguardian` dependency). If `GITGUARDIAN_SOURCE_UUID` is set, a detected secret also creates a real incident via [`/v1/scan/create-incidents`](https://api.gitguardian.com/docs#tag/Scan-Methods/operation/scan_create_incidents).
- The upstream call is real, via each provider's official SDK, routed by a prefix on the model name: `openai/gpt-4o-mini`, `anthropic/claude-haiku-4-5`, `mistral/mistral-small-latest` (same convention as LiteLLM).
- Streaming (`"stream": true`) works, but buffers the full completion, scans it, then flushes it to the client as SSE. A leaked secret can't be un-sent once streamed token-by-token, so this trades true low-latency streaming for keeping the fail-closed guarantee intact.

## Setup

Requires [`uv`](https://docs.astral.sh/uv/), a GitGuardian personal access token (`scan` scope, plus `scan:create-incidents` if `GITGUARDIAN_SOURCE_UUID` is set, created in the dashboard under API > Personal access tokens: [US SaaS](https://dashboard.gitguardian.com/api/personal-access-tokens), [EU SaaS](https://dashboard.eu1.gitguardian.com/api/personal-access-tokens)), and at least one of `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `MISTRAL_API_KEY`.

```bash
uv sync
cp .env.example .env
```

Edit `.env`: set `GITGUARDIAN_API_KEY` and whichever provider key(s) you have. `GITGUARDIAN_API_URL` and `GITGUARDIAN_SOURCE_UUID` are optional (see `.env.example`). All env vars are parsed and validated in one place, `app/config.py`'s `load_settings()`, which fails fast at startup if something's missing.

```bash
uv run --env-file .env uvicorn app.main:app --reload
```

`GET /healthz` returns `{"status": "ok"}` once the gateway is up.

## Demo

**1. Clean prompt:**

```bash
curl -s localhost:8000/v1/chat/completions \
  --json '{"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "What is the capital of France?"}]}' | python3 -m json.tool
```

Streamed (`-N` so curl doesn't buffer):

```bash
curl -s -N localhost:8000/v1/chat/completions \
  --json '{"model": "anthropic/claude-haiku-4-5", "messages": [{"role": "user", "content": "What is the capital of France?"}], "stream": true}'
```

**2. Secret in the prompt - blocked before reaching the provider:**

```bash
FAKE_TOKEN="ghp_$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36)))')"
curl -s localhost:8000/v1/chat/completions \
  --json "{\"model\": \"openai/gpt-4o-mini\", \"messages\": [{\"role\": \"user\", \"content\": \"Here is my token $FAKE_TOKEN, can you debug this script?\"}]}" | python3 -m json.tool
```

Returns `400 secret_detected_in_request`; the provider is never called.

**3. Secret in the completion - blocked before reaching the caller.** A live model won't reliably produce a detectable secret on request (it either needs the secret fed to it, which just re-tests case 2, or it free-generates low-entropy patterned text that GitGuardian ignores as noise). So this mocks only the upstream call - everything else, including the real GitGuardian scan, runs unmodified - to simulate a model leaking a memorized credential:

```bash
uv run --env-file .env python3 -c "
import asyncio, secrets, string
from unittest.mock import patch

fake_token = 'ghp_' + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36))

async def fake_call_upstream(model, messages, settings):
    return f'Sure! Here is an example token: {fake_token}. Hope that helps!'

async def main():
    import app.main as main
    with patch('app.main.call_upstream', side_effect=fake_call_upstream):
        from fastapi.testclient import TestClient
        with TestClient(main.app) as client:
            r = client.post('/v1/chat/completions', json={
                'model': 'openai/gpt-4o-mini',
                'messages': [{'role': 'user', 'content': 'Give me an example API key.'}],
            })
            print(r.status_code, r.json())

asyncio.run(main())
"
```

Returns `502 secret_detected_in_response`; the leaked completion is never returned to the client.

**4. Unsupported provider - rejected up front:**

```bash
curl -s localhost:8000/v1/chat/completions \
  --json '{"model": "cohere/command-r", "messages": [{"role": "user", "content": "hi"}]}' | python3 -m json.tool
```

Returns `400 unsupported_model`.

## Lint and type-check

```bash
uv run ruff check .
uv run ruff format .
uv run ty check .
```

## Notes

- `/multiscan` takes ~20 documents per call by default - fine for one chat turn per request.
- `/scan/create-incidents` needs a `source_uuid` (a GitGuardian custom source). Incident creation is best-effort and never overrides the fail-closed block if it fails. Put the gateway behind an authenticating proxy that sets `X-Forwarded-User` and `X-Forwarded-Email` (e.g. oauth2-proxy) and incidents record who sent the request.
