import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import Settings, load_settings
from app.constants import HTTP_TIMEOUT_SECONDS, INCIDENT_LOCATION_PREFIX
from app.secret_scanner import (
    Author,
    GitGuardianClient,
    SecretFinding,
    SecretScanError,
    create_incidents_for_findings,
    scan_documents,
)
from app.sse import build_sse_stream
from app.upstream import UpstreamError, call_upstream

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_gateway")

settings: Settings | None = None
gg_client: GitGuardianClient | None = None
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global settings, gg_client, http_client
    settings = load_settings()
    http_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
    gg_client = GitGuardianClient(
        http_client,
        api_key=settings.gitguardian_api_key,
        api_url=settings.api_url,
    )
    await gg_client.health_check()
    logger.info("GitGuardian API reachable, secret scanning enabled")
    if not settings.gitguardian_source_uuid:
        logger.warning(
            "GITGUARDIAN_SOURCE_UUID not set; detected secrets will still be "
            "blocked, but no GitGuardian incident will be created for them."
        )
    yield
    await http_client.aclose()


app = FastAPI(title="AI Gateway - GitGuardian secret-scanning demo", lifespan=lifespan)


def _get_settings() -> Settings:
    if settings is None:
        raise RuntimeError("Settings not initialized - app lifespan has not started")
    return settings


def _get_gg_client() -> GitGuardianClient:
    if gg_client is None:
        raise RuntimeError("GitGuardian client not initialized - app lifespan has not started")
    return gg_client


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


async def _create_incidents_if_configured(
    labeled_contents: list[tuple[str, str]], findings: list[SecretFinding], author: Author
) -> None:
    source_uuid = _get_settings().gitguardian_source_uuid
    if not source_uuid:
        return
    try:
        await create_incidents_for_findings(
            _get_gg_client(),
            labeled_contents,
            findings,
            source_uuid,
            INCIDENT_LOCATION_PREFIX,
            author,
        )
        logger.info("Created GitGuardian incident(s) for %d finding(s)", len(findings))
    except SecretScanError as exc:
        logger.error("Failed to create GitGuardian incident(s): %s", exc)


@app.post("/v1/chat/completions")
async def chat_completions(
    payload: ChatRequest,
    # Set by an authenticating reverse proxy in front of the gateway, e.g. oauth2-proxy.
    x_forwarded_user: str | None = Header(default=None),
    x_forwarded_email: str | None = Header(default=None),
):
    author = Author(name=x_forwarded_user, email=x_forwarded_email)
    current_settings = _get_settings()
    current_gg_client = _get_gg_client()

    request_labeled = [
        (f"request/message[{i}].{m.role}", m.content) for i, m in enumerate(payload.messages)
    ]

    try:
        request_findings = await scan_documents(current_gg_client, request_labeled)
    except SecretScanError as exc:
        return JSONResponse(status_code=httpx.codes.BAD_GATEWAY, content={"error": str(exc)})

    if request_findings:
        logger.warning("Blocked outbound request: %s", request_findings)
        await _create_incidents_if_configured(request_labeled, request_findings, author)
        return JSONResponse(
            status_code=httpx.codes.BAD_REQUEST,
            content={
                "error": "secret_detected_in_request",
                "message": (
                    "This request was blocked because GitGuardian detected a "
                    "secret in the prompt. Nothing was forwarded upstream."
                ),
                "findings": [f.to_dict() for f in request_findings],
            },
        )

    try:
        reply_text = await call_upstream(
            payload.model, [m.model_dump() for m in payload.messages], current_settings
        )
    except UpstreamError as exc:
        return JSONResponse(
            status_code=httpx.codes.BAD_REQUEST,
            content={"error": "unsupported_model", "message": str(exc)},
        )

    response_labeled = [("response/message[0].assistant", reply_text)]
    try:
        response_findings = await scan_documents(current_gg_client, response_labeled)
    except SecretScanError as exc:
        return JSONResponse(status_code=httpx.codes.BAD_GATEWAY, content={"error": str(exc)})

    if response_findings:
        logger.warning("Blocked inbound completion: %s", response_findings)
        await _create_incidents_if_configured(response_labeled, response_findings, author)
        return JSONResponse(
            status_code=httpx.codes.BAD_GATEWAY,
            content={
                "error": "secret_detected_in_response",
                "message": (
                    "The upstream model's response was blocked because "
                    "GitGuardian detected a secret in it. It was not "
                    "returned to the caller."
                ),
                "findings": [f.to_dict() for f in response_findings],
            },
        )

    if payload.stream:
        return StreamingResponse(
            build_sse_stream(payload.model, reply_text), media_type="text/event-stream"
        )

    return {
        "model": payload.model,
        "choices": [{"message": {"role": "assistant", "content": reply_text}}],
    }
