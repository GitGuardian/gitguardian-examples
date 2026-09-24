"""HTTP requests that ride out rate limits and transient failures."""

import asyncio
import logging
import random
import time

import httpx

from app.constants import BACKOFF_BASE_SECONDS, BACKOFF_MAX_SECONDS, HTTP_MAX_ATTEMPTS

logger = logging.getLogger(__name__)


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter, so concurrent clients don't retry in lockstep."""
    delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2**attempt)
    return delay / 2 + random.uniform(0, delay / 2)


def _retry_delay(response: httpx.Response, attempt: int) -> float | None:
    """Seconds to wait before retrying, or None if the response shouldn't be retried.

    https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#handle-rate-limit-errors-appropriately
    """
    headers = response.headers
    if response.status_code not in (403, 429) and response.status_code < 500:
        return None
    if retry_after := headers.get("retry-after"):
        return float(retry_after)
    if headers.get("x-ratelimit-remaining") == "0" and (reset := headers.get("x-ratelimit-reset")):
        return max(float(reset) - time.time(), 0) + 1
    if response.status_code == 403:
        # GitHub's secondary rate limit can come without headers; a plain 403 is a permission error.
        if "rate limit" not in response.text.lower():
            return None
        return max(60, _backoff(attempt))
    return _backoff(attempt)


async def request(http: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Send a request, retrying rate-limited, 5xx and network failures up to HTTP_MAX_ATTEMPTS."""
    for attempt in range(HTTP_MAX_ATTEMPTS):
        last_attempt = attempt == HTTP_MAX_ATTEMPTS - 1
        try:
            response = await http.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if last_attempt:
                raise
            delay = _backoff(attempt)
            logger.warning(
                "Request failed, retrying",
                extra={
                    "method": method,
                    "url": url,
                    "error": str(exc),
                    "retry_in_seconds": round(delay, 1),
                },
            )
            await asyncio.sleep(delay)
            continue

        delay = _retry_delay(response, attempt)
        if delay is None or last_attempt:
            return response
        logger.warning(
            "Request rate limited or failed, retrying",
            extra={
                "method": method,
                "url": url,
                "status_code": response.status_code,
                "retry_in_seconds": round(delay, 1),
            },
        )
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")
