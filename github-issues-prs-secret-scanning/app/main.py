import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from app.config import ConfigError, WebhookSettings, load_webhook_settings
from app.constants import HTTP_TIMEOUT_SECONDS
from app.github import verify_signature, webhook_document
from app.logs import setup_logging
from app.models import Model
from app.secret_scanner import GitGuardianClient, SecretFinding, SecretScanError, scan_documents

setup_logging()
logger = logging.getLogger("github_webhook")

settings: WebhookSettings | None = None
gg_client: GitGuardianClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global settings, gg_client
    settings = load_webhook_settings()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http_client:
        gg_client = GitGuardianClient(
            http_client,
            api_key=settings.gitguardian.api_key,
            api_url=settings.gitguardian.api_url,
        )
        yield


app = FastAPI(
    title="GitHub Issues & PRs - GitGuardian secret-scanning demo",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _get_settings() -> WebhookSettings:
    if settings is None:
        raise RuntimeError("Settings not initialized - app lifespan has not started")
    return settings


def _get_gg_client() -> GitGuardianClient:
    if gg_client is None:
        raise RuntimeError("GitGuardian client not initialized - app lifespan has not started")
    return gg_client


class WebhookResponse(Model):
    status: Literal["ignored", "clean", "secret_detected"]
    findings: list[SecretFinding] = []


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(),
    x_hub_signature_256: str | None = Header(default=None),
) -> WebhookResponse:
    current_settings = _get_settings()
    # Read raw rather than as a pydantic body parameter: the signature is over the exact bytes.
    body = await request.body()
    if not verify_signature(current_settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=httpx.codes.UNAUTHORIZED, detail="invalid_signature")

    try:
        document = webhook_document(x_github_event, body)
    except ValidationError as exc:
        logger.warning(
            "Invalid webhook payload", extra={"event": x_github_event, "error": str(exc)}
        )
        raise HTTPException(status_code=httpx.codes.BAD_REQUEST, detail="invalid_payload") from exc
    if document is None:
        return WebhookResponse(status="ignored")

    try:
        findings = await scan_documents(
            _get_gg_client(), [document], current_settings.gitguardian.source_uuid
        )
    except SecretScanError as exc:
        # A non-2xx makes the delivery show as failed in GitHub, so it can be redelivered.
        logger.error("Scan failed", extra={"url": document.location.url, "error": str(exc)})
        raise HTTPException(status_code=httpx.codes.BAD_GATEWAY, detail=str(exc)) from exc

    return WebhookResponse(status="secret_detected" if findings else "clean", findings=findings)


async def _check_gitguardian(settings: WebhookSettings) -> None:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http_client:
        client = GitGuardianClient(
            http_client, settings.gitguardian.api_key, settings.gitguardian.api_url
        )
        await client.health_check()


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive GitHub webhooks and scan them.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Checked before uvicorn starts: a failure inside the app's lifespan gets a uvicorn traceback.
    try:
        asyncio.run(_check_gitguardian(load_webhook_settings()))
    except (ConfigError, SecretScanError) as exc:
        logger.error("Startup failed", extra={"error": str(exc)})
        raise SystemExit(1) from exc
    logger.info("GitGuardian API reachable, secret scanning enabled")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
