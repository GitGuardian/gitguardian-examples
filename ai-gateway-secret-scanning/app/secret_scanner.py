from dataclasses import asdict, dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field


class SecretScanError(RuntimeError):
    """Raised when the GitGuardian API could not be reached or returned an error."""


class ScanMatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # The API calls this field "type" (e.g. "apikey"); we alias it to
    # match_type since "type" collides in meaning with PolicyBreak's own
    # "type" field (the human-readable detector label).
    match_type: str = Field(alias="type")
    line_start: int | None = None


class PolicyBreak(BaseModel):
    policy: str
    detector_name: str | None = None
    matches: list[ScanMatch] = []

    @property
    def is_secret(self) -> bool:
        return self.policy == "Secrets detection"


class ScanResult(BaseModel):
    policy_break_count: int
    policy_breaks: list[PolicyBreak] = []


@dataclass
class SecretFinding:
    document_label: str
    detector_name: str
    match_type: str
    line_start: int | None

    def to_dict(self) -> dict:
        return asdict(self)


class GitGuardianClient:
    """Thin wrapper around the GitGuardian REST API (no pygitguardian dependency).

    https://api.gitguardian.com/docs#tag/Scan-Methods/operation/multiple_scan
    https://api.gitguardian.com/docs#tag/Scan-Methods/operation/scan_create_incidents
    """

    def __init__(self, http_client: httpx.AsyncClient, api_key: str, api_url: str):
        self._http = http_client
        self._api_url = api_url.rstrip("/")
        self._headers = {
            "Authorization": f"Token {api_key}",
            "User-Agent": "ai-gateway-demo",
        }

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            return str(response.json().get("detail", response.text))
        except ValueError:
            return response.text

    async def health_check(self) -> None:
        response = await self._http.get(f"{self._api_url}/v1/health", headers=self._headers)
        if response.status_code != httpx.codes.OK:
            raise SecretScanError(
                f"GitGuardian health check against {self._api_url} failed "
                f"({response.status_code}): {self._error_detail(response)}. "
                "If your workspace is on another region or self-hosted, set GITGUARDIAN_API_URL."
            )

    async def multiscan(self, documents: list[dict]) -> list[ScanResult]:
        response = await self._http.post(
            f"{self._api_url}/v1/multiscan", headers=self._headers, json=documents
        )
        if response.status_code != httpx.codes.OK:
            raise SecretScanError(
                f"GitGuardian multiscan error ({response.status_code}): "
                f"{self._error_detail(response)}"
            )
        return [ScanResult.model_validate(item) for item in response.json()]

    async def create_incidents(self, documents: list[dict], source_uuid: str) -> list[ScanResult]:
        payload = {"source_uuid": source_uuid, "documents": documents}
        response = await self._http.post(
            f"{self._api_url}/v1/scan/create-incidents",
            headers=self._headers,
            json=payload,
        )
        if response.status_code != httpx.codes.OK:
            raise SecretScanError(
                f"GitGuardian create-incidents error ({response.status_code}): "
                f"{self._error_detail(response)}"
            )
        return [ScanResult.model_validate(item) for item in response.json()]


async def scan_documents(
    client: GitGuardianClient, labeled_contents: list[tuple[str, str]]
) -> list[SecretFinding]:
    """Scan a batch of labeled text blobs via GitGuardian's /multiscan endpoint.

    labeled_contents: list of (label, content) pairs, e.g.
        ("request/message[0].user", "here's my api key: ...")

    Returns a flat list of findings (empty if nothing was detected).
    """
    if not labeled_contents:
        return []

    documents = [
        {"document": content, "filename": f"{label}.txt"} for label, content in labeled_contents
    ]

    scan_results = await client.multiscan(documents)

    findings: list[SecretFinding] = []
    for (label, _content), scan_result in zip(labeled_contents, scan_results, strict=True):
        for policy_break in scan_result.policy_breaks:
            if not policy_break.is_secret:
                continue
            for match in policy_break.matches:
                findings.append(
                    SecretFinding(
                        document_label=label,
                        detector_name=policy_break.detector_name or policy_break.policy,
                        match_type=match.match_type,
                        line_start=match.line_start,
                    )
                )
    return findings


async def create_incidents_for_findings(
    client: GitGuardianClient,
    labeled_contents: list[tuple[str, str]],
    findings: list[SecretFinding],
    source_uuid: str,
    location_prefix: str,
) -> None:
    """Create real GitGuardian incidents for the documents that had findings.

    https://api.gitguardian.com/docs#tag/Scan-Methods/operation/scan_create_incidents
    """
    flagged_labels = {f.document_label for f in findings}
    documents = [
        {
            "document": content,
            "filename": f"{label}.txt",
            "location": {"url": f"{location_prefix}#{label}"},
        }
        for label, content in labeled_contents
        if label in flagged_labels
    ]
    if not documents:
        return

    await client.create_incidents(documents, source_uuid=source_uuid)
