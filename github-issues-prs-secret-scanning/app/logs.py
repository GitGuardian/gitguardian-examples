"""Logging with constant messages and the variable parts as structured attributes.

logger.info("Backfill finished", extra={"documents": 12, "secrets": 1})
INFO github_backfill: Backfill finished {"documents": 12, "secrets": 1}
"""

import json
import logging

_RECORD_ATTRIBUTES = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class ExtraFormatter(logging.Formatter):
    """Append the attributes passed through `extra` to the line, as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extra = {k: v for k, v in record.__dict__.items() if k not in _RECORD_ATTRIBUTES}
        return f"{line} {json.dumps(extra, default=str)}" if extra else line


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ExtraFormatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)
