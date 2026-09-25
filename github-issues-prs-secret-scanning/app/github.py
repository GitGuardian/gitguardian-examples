"""Turn GitHub issues, pull requests, comments and reviews into documents to scan.

Webhook payloads and REST API responses share the same object shapes, so the same
models serve both the webhook receiver and the backfill command.
"""

import hashlib
import hmac
import logging
from collections.abc import AsyncIterator

import httpx

from app import retry
from app.constants import GITHUB_PAGE_SIZE, USER_AGENT
from app.models import Model
from app.secret_scanner import Document, DocumentLocation

logger = logging.getLogger(__name__)


class User(Model):
    login: str


class UserProfile(Model):
    # Only set when the user made their email public.
    email: str | None = None


def _document(filename: str, content: str, url: str, author: User | None) -> Document:
    return Document(
        filename=filename,
        document=content,
        location=DocumentLocation(url=url),
        author_name=author.login if author else None,
    )


class Issue(Model):
    """An issue, or a pull request as the issues API lists it."""

    number: int
    title: str
    body: str | None = None
    html_url: str
    user: User | None = None
    # Only set when the issue is a pull request.
    pull_request: dict | None = None

    def document(self, repo: str) -> Document:
        kind = "pull" if self.pull_request is not None else "issues"
        return _document(
            f"{repo}/{kind}/{self.number}",
            f"{self.title}\n\n{self.body or ''}",
            self.html_url,
            self.user,
        )


class PullRequest(Model):
    number: int
    title: str
    body: str | None = None
    html_url: str
    user: User | None = None

    def document(self, repo: str) -> Document:
        return _document(
            f"{repo}/pull/{self.number}",
            f"{self.title}\n\n{self.body or ''}",
            self.html_url,
            self.user,
        )


class IssueComment(Model):
    """A comment on the conversation of an issue or a pull request."""

    id: int
    body: str | None = None
    html_url: str
    user: User | None = None

    def document(self, repo: str) -> Document:
        return _document(
            f"{repo}/issues/comments/{self.id}", self.body or "", self.html_url, self.user
        )


class ReviewComment(IssueComment):
    """An inline comment left on a pull request's diff."""

    def document(self, repo: str) -> Document:
        return _document(
            f"{repo}/pulls/comments/{self.id}", self.body or "", self.html_url, self.user
        )


class Review(IssueComment):
    """The top-level body of a pull request review."""

    def document(self, repo: str) -> Document:
        return _document(
            f"{repo}/pulls/reviews/{self.id}", self.body or "", self.html_url, self.user
        )


class Repository(Model):
    full_name: str


class WebhookEvent(Model):
    action: str
    repository: Repository

    def document(self) -> Document:
        raise NotImplementedError


class IssuesEvent(WebhookEvent):
    issue: Issue

    def document(self) -> Document:
        return self.issue.document(self.repository.full_name)


class PullRequestEvent(WebhookEvent):
    pull_request: PullRequest

    def document(self) -> Document:
        return self.pull_request.document(self.repository.full_name)


class IssueCommentEvent(WebhookEvent):
    comment: IssueComment

    def document(self) -> Document:
        return self.comment.document(self.repository.full_name)


class PullRequestReviewEvent(WebhookEvent):
    review: Review

    def document(self) -> Document:
        return self.review.document(self.repository.full_name)


class PullRequestReviewCommentEvent(WebhookEvent):
    comment: ReviewComment

    def document(self) -> Document:
        return self.comment.document(self.repository.full_name)


# X-GitHub-Event header -> payload model and the actions worth scanning.
WEBHOOK_EVENTS: dict[str, tuple[type[WebhookEvent], set[str]]] = {
    "issues": (IssuesEvent, {"opened", "edited"}),
    "pull_request": (PullRequestEvent, {"opened", "edited"}),
    "issue_comment": (IssueCommentEvent, {"created", "edited"}),
    "pull_request_review": (PullRequestReviewEvent, {"submitted", "edited"}),
    "pull_request_review_comment": (PullRequestReviewCommentEvent, {"created", "edited"}),
}


class _Action(Model):
    action: str | None = None


def webhook_document(event: str, body: bytes) -> Document | None:
    """The document carried by a webhook delivery, or None if the event isn't scanned."""
    if event not in WEBHOOK_EVENTS:
        return None
    model, actions = WEBHOOK_EVENTS[event]
    if _Action.model_validate_json(body).action not in actions:
        return None
    return model.model_validate_json(body).document()


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Check the X-Hub-Signature-256 header GitHub sends with every webhook delivery.

    https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
    """
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class GitHubError(RuntimeError):
    """Raised when the GitHub API returned an error the backfill can't recover from."""


class GitHubClient:
    """Read-only client for the GitHub REST API calls the backfill and webhook need."""

    def __init__(self, http_client: httpx.AsyncClient, token: str, api_url: str):
        self._http = http_client
        self._api_url = api_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        }
        self._emails: dict[str, str | None] = {}

    async def _paginate[T: Model](
        self, path: str, model: type[T], params: dict | None = None
    ) -> AsyncIterator[T]:
        url: str | None = f"{self._api_url}{path}"
        query = {"per_page": GITHUB_PAGE_SIZE, **(params or {})}
        while url:
            response = await retry.request(
                self._http, "GET", url, headers=self._headers, params=query
            )
            if response.status_code != httpx.codes.OK:
                raise GitHubError(
                    f"GitHub returned {response.status_code} for {url}. Check that GITHUB_TOKEN "
                    "can read this repository's issues and pull requests."
                )
            for item in response.json():
                yield model.model_validate(item)
            # The "next" link already carries every query parameter.
            url = response.links.get("next", {}).get("url")
            query = None

    async def _public_email(self, login: str) -> str | None:
        if login not in self._emails:
            url = f"{self._api_url}/users/{login}"
            response = await retry.request(self._http, "GET", url, headers=self._headers)
            if response.status_code != httpx.codes.OK:
                logger.warning(
                    "Author email lookup failed",
                    extra={"login": login, "status_code": response.status_code},
                )
                return None
            email = UserProfile.model_validate_json(response.content).email
            is_noreply = email is not None and "noreply" in email.rpartition("@")[2]
            self._emails[login] = None if is_noreply else email
        return self._emails[login]

    async def with_author_email(self, document: Document) -> Document:
        """The document with its author's public email as author_info, when they have one."""
        if document.author_name is None:
            return document
        email = await self._public_email(document.author_name)
        return document.model_copy(update={"author_info": email}) if email else document

    async def repository_documents(
        self, repo: str, since: str | None = None
    ) -> AsyncIterator[Document]:
        """Every issue, pull request, comment and review of a repository.

        since: ISO 8601 timestamp; only content updated after it is returned. Reviews
        have no such filter, so they are fetched for every pull request updated since then.
        """
        since_param = {"since": since} if since else {}
        pull_numbers: list[int] = []

        async for issue in self._paginate(
            f"/repos/{repo}/issues", Issue, {"state": "all", **since_param}
        ):
            if issue.pull_request is not None:
                pull_numbers.append(issue.number)
            yield issue.document(repo)

        async for comment in self._paginate(
            f"/repos/{repo}/issues/comments", IssueComment, since_param
        ):
            yield comment.document(repo)

        async for comment in self._paginate(
            f"/repos/{repo}/pulls/comments", ReviewComment, since_param
        ):
            yield comment.document(repo)

        for number in pull_numbers:
            async for review in self._paginate(f"/repos/{repo}/pulls/{number}/reviews", Review):
                yield review.document(repo)
