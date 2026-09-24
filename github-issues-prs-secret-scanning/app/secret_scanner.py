import logging
from collections.abc import Iterator

import httpx
from pydantic import ConfigDict, Field, TypeAdapter

from app import retry
from app.constants import MAX_BATCH_BYTES, MAX_DOCUMENTS_PER_SCAN, USER_AGENT
from app.models import Model

logger = logging.getLogger(__name__)


class SecretScanError(RuntimeError):
    """Raised when the GitGuardian API could not be reached or returned an error."""


class DocumentLocation(Model):
    url: str


class Document(Model):
    """One piece of GitHub content to scan: an issue/PR body, a comment or a review."""

    filename: str
    document: str
    location: DocumentLocation


class CreateIncidentsRequest(Model):
    source_uuid: str
    documents: list[Document]


class ScanMatch(Model):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    # The API calls this field "type" (e.g. "apikey"); aliased because PolicyBreak
    # has its own, unrelated "type" field (the human-readable detector label).
    match_type: str = Field(alias="type")
    line_start: int | None = None


class PolicyBreak(Model):
    policy: str
    detector_name: str | None = None
    matches: list[ScanMatch] = []

    @property
    def is_secret(self) -> bool:
        return self.policy == "Secrets detection"


class ScanResult(Model):
    policy_break_count: int
    policy_breaks: list[PolicyBreak] = []


ScanResults = TypeAdapter(list[ScanResult])


class SecretFinding(Model):
    """One detected secret, with the parts GitGuardian matched (e.g. username, password)."""

    url: str
    detector_name: str
    line_start: int | None
    parts: list[str]


class GitGuardianClient:
    """Thin wrapper around the GitGuardian REST API (no pygitguardian dependency).

    https://api.gitguardian.com/docs#tag/Scan-Methods/operation/scan_create_incidents
    """

    def __init__(self, http_client: httpx.AsyncClient, api_key: str, base_url: str):
        self._http = http_client
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Token {api_key}", "User-Agent": USER_AGENT}

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            return str(response.json().get("detail", response.text))
        except ValueError:
            return response.text

    async def health_check(self) -> None:
        response = await retry.request(
            self._http, "GET", f"{self._base_url}/v1/health", headers=self._headers
        )
        if response.status_code != 200:
            raise SecretScanError(
                f"GitGuardian health check against {self._base_url} failed "
                f"({response.status_code}): {self._error_detail(response).rstrip('.')}. "
                "If your workspace is on another region or self-hosted, set GITGUARDIAN_API_URL."
            )

    async def create_incidents(self, request: CreateIncidentsRequest) -> list[ScanResult]:
        """Scan documents and raise an incident on the custom source for every secret found.

        Returns one scan result per document, in the same order.
        """
        response = await retry.request(
            self._http,
            "POST",
            f"{self._base_url}/v1/scan/create-incidents",
            headers=self._headers,
            json=request.model_dump(mode="json"),
        )
        if response.status_code != 200:
            raise SecretScanError(
                f"GitGuardian create-incidents error ({response.status_code}): "
                f"{self._error_detail(response)}"
            )
        return ScanResults.validate_json(response.content)


def _batches(documents: list[Document]) -> Iterator[list[Document]]:
    """Group documents so each request stays under both the document count and body size caps."""
    batch: list[Document] = []
    batch_size = 0
    for document in documents:
        size = len(document.document.encode())
        if batch and (len(batch) == MAX_DOCUMENTS_PER_SCAN or batch_size + size > MAX_BATCH_BYTES):
            yield batch
            batch, batch_size = [], 0
        batch.append(document)
        batch_size += size
    if batch:
        yield batch


async def scan_documents(
    client: GitGuardianClient, documents: list[Document], source_uuid: str
) -> list[SecretFinding]:
    """Scan documents, raising GitGuardian incidents on the custom source for every secret."""
    findings: list[SecretFinding] = []
    for batch in _batches([d for d in documents if d.document.strip()]):
        request = CreateIncidentsRequest(source_uuid=source_uuid, documents=batch)
        scan_results = await client.create_incidents(request)
        for document, scan_result in zip(batch, scan_results, strict=True):
            findings.extend(
                SecretFinding(
                    url=document.location.url,
                    detector_name=policy_break.detector_name or policy_break.policy,
                    line_start=min(
                        (m.line_start for m in policy_break.matches if m.line_start is not None),
                        default=None,
                    ),
                    parts=[m.match_type for m in policy_break.matches],
                )
                for policy_break in scan_result.policy_breaks
                if policy_break.is_secret
            )
    for finding in findings:
        logger.warning("Secret detected", extra=finding.model_dump())
    return findings
