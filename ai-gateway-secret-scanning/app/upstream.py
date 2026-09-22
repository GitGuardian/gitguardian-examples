from typing import cast

from anthropic import AsyncAnthropic, omit
from anthropic.types import MessageParam
from mistralai.client import Mistral
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.config import Settings
from app.constants import (
    ANTHROPIC_MAX_TOKENS,
    DEMO_MODEL_ANTHROPIC,
    DEMO_MODEL_MISTRAL,
    DEMO_MODEL_OPENAI,
    Provider,
)


class UpstreamError(RuntimeError):
    """Raised when the requested model can't be routed to a supported provider."""


async def call_upstream(model: str, messages: list[dict[str, str]], settings: Settings) -> str:
    """Call the real upstream provider and return the full completion text.

    `model` must be prefixed with the provider, e.g. DEMO_MODEL_OPENAI,
    DEMO_MODEL_ANTHROPIC, or DEMO_MODEL_MISTRAL (the same "<provider>/<model>"
    convention LiteLLM uses). The call always streams from the provider so
    the demo genuinely exercises a streaming code path, but this function
    buffers the full response before returning it - GitGuardian scans the
    complete text before anything is forwarded to the caller.
    """
    provider, _, real_model = model.partition("/")

    if provider == Provider.OPENAI:
        return await _call_openai(real_model, messages, settings.openai_api_key)
    if provider == Provider.ANTHROPIC:
        return await _call_anthropic(real_model, messages, settings.anthropic_api_key)
    if provider == Provider.MISTRAL:
        return await _call_mistral(real_model, messages, settings.mistral_api_key)

    raise UpstreamError(
        f"Unsupported model '{model}': prefix the model with its provider, "
        f"e.g. '{DEMO_MODEL_OPENAI}', '{DEMO_MODEL_ANTHROPIC}', or '{DEMO_MODEL_MISTRAL}'."
    )


async def _call_openai(model: str, messages: list[dict[str, str]], api_key: str | None) -> str:
    async with AsyncOpenAI(api_key=api_key) as client:
        stream = await client.chat.completions.create(
            model=model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            stream=True,
        )

        chunks: list[str] = []
        async for event in stream:
            delta = event.choices[0].delta.content
            if delta:
                chunks.append(delta)
        return "".join(chunks)


async def _call_anthropic(model: str, messages: list[dict[str, str]], api_key: str | None) -> str:
    async with AsyncAnthropic(api_key=api_key) as client:
        system_prompt = "\n".join(m["content"] for m in messages if m["role"] == "system")
        conversation = [m for m in messages if m["role"] != "system"]

        chunks: list[str] = []
        async with client.messages.stream(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system_prompt if system_prompt else omit,
            messages=cast(list[MessageParam], conversation),
        ) as stream:
            async for text in stream.text_stream:
                chunks.append(text)
        return "".join(chunks)


async def _call_mistral(model: str, messages: list[dict[str, str]], api_key: str | None) -> str:
    client = Mistral(api_key=api_key)
    stream = await client.chat.stream_async(model=model, messages=messages)

    chunks: list[str] = []
    async for event in stream:
        delta_content = event.data.choices[0].delta.content
        if isinstance(delta_content, str):
            chunks.append(delta_content)
    return "".join(chunks)
