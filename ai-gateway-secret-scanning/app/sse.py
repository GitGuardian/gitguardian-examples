import re
import uuid
from collections.abc import Iterator

from pydantic import BaseModel

from app.constants import SSE_FRAGMENT_MAX_LEN


class ChunkDelta(BaseModel):
    content: str | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: ChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    """OpenAI-style chat-completion-chunk SSE payload."""

    id: str
    object: str = "chat.completion.chunk"
    model: str
    choices: list[ChunkChoice]


def _split_into_fragments(text: str) -> list[str]:
    """Split text into small pieces so a client sees multiple SSE frames.

    The full completion is already scanned and buffered by this point (see
    call_upstream's buffer-then-flush design), so this is purely so the
    client-facing API genuinely emits a stream of chunks rather than one
    giant frame - not an attempt at real token-level pacing.
    """
    words = re.findall(r"\S+\s*", text)
    fragments = []
    current = ""
    for word in words:
        if current and len(current) + len(word) > SSE_FRAGMENT_MAX_LEN:
            fragments.append(current)
            current = ""
        current += word
    if current:
        fragments.append(current)
    return fragments or [text]


def build_sse_stream(model: str, text: str) -> Iterator[bytes]:
    """Yield an OpenAI-style SSE chat-completion-chunk stream for `text`."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    for fragment in _split_into_fragments(text):
        chunk = ChatCompletionChunk(
            id=completion_id,
            model=model,
            choices=[ChunkChoice(delta=ChunkDelta(content=fragment))],
        )
        yield f"data: {chunk.model_dump_json()}\n\n".encode()

    final_chunk = ChatCompletionChunk(
        id=completion_id,
        model=model,
        choices=[ChunkChoice(delta=ChunkDelta(), finish_reason="stop")],
    )
    yield f"data: {final_chunk.model_dump_json()}\n\n".encode()
    yield b"data: [DONE]\n\n"
