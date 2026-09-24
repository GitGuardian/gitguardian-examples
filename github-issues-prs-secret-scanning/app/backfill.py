"""Scan the existing issues, pull requests, comments and reviews of a GitHub repository.

uv run --env-file .env backfill OWNER/REPO [--since 2026-01-01T00:00:00Z]
"""

import argparse
import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx

from app.config import ConfigError, load_backfill_settings
from app.github import GitHubClient, GitHubError
from app.logs import setup_logging
from app.secret_scanner import Document, GitGuardianClient, SecretScanError, scan_documents

# Documents collected from GitHub before each scan.
CHUNK_SIZE = 100

logger = logging.getLogger("github_backfill")


async def backfill(repo: str, since: str | None) -> tuple[int, int]:
    """Scan a repository; returns how many documents were scanned and secrets found."""
    settings = load_backfill_settings()
    source_uuid = settings.gitguardian.source_uuid

    async with httpx.AsyncClient(timeout=20) as http_client:
        gg_client = GitGuardianClient(
            http_client, settings.gitguardian.api_key, settings.gitguardian.base_url
        )
        github = GitHubClient(http_client, settings.github_token, settings.github_api_url)
        await gg_client.health_check()

        scanned = findings_count = 0
        chunk: list[Document] = []

        async def flush() -> None:
            nonlocal scanned, findings_count
            findings = await scan_documents(gg_client, chunk, source_uuid)
            scanned += len(chunk)
            findings_count += len(findings)
            chunk.clear()
            logger.info(
                "Backfill progress",
                extra={"repo": repo, "documents": scanned, "secrets": findings_count},
            )

        async for document in github.repository_documents(repo, since):
            chunk.append(document)
            if len(chunk) >= CHUNK_SIZE:
                await flush()
        if chunk:
            await flush()

    return scanned, findings_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan the existing issues and pull requests of a GitHub repository."
    )
    parser.add_argument("repo", help="Repository to scan, as OWNER/REPO")
    parser.add_argument("--since", help="Only scan content updated after this ISO 8601 timestamp")
    args = parser.parse_args()
    setup_logging()

    started_at = datetime.now(UTC)
    start = time.monotonic()
    logger.info(
        "Backfill started",
        extra={"repo": args.repo, "since": args.since, "started_at": started_at.isoformat()},
    )

    def timing() -> dict:
        return {
            "repo": args.repo,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - start, 1),
        }

    try:
        scanned, findings_count = asyncio.run(backfill(args.repo, args.since))
    except (ConfigError, GitHubError, SecretScanError) as exc:
        logger.error("Backfill failed", extra={**timing(), "error": str(exc)})
        raise SystemExit(2) from exc
    logger.info(
        "Backfill finished", extra={**timing(), "documents": scanned, "secrets": findings_count}
    )
    raise SystemExit(1 if findings_count else 0)


if __name__ == "__main__":
    main()
