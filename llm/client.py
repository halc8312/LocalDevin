"""Ollama OpenAI-compatible LLM client."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, APIConnectionError, APIStatusError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


class LLMClient:
    """Async LLM client that targets an Ollama OpenAI-compatible endpoint.

    Wraps the ``openai`` Python library with retry logic and optional
    structured-output (JSON → Pydantic model) support.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        token_tracker: object | None = None,
        session_id: str | None = None,
    ) -> None:
        """Initialise the client.

        Args:
            base_url: Ollama API base URL (must end with ``/v1``).
            api_key: Dummy API key accepted by Ollama.
            token_tracker: Optional token tracker instance for recording usage.
            session_id: Optional session ID to associate token usage with.
        """
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._token_tracker = token_tracker
        self._session_id = session_id

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send a chat request and return the response text.

        Args:
            messages: List of OpenAI-format message dicts.
            model: Model name to use.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            The assistant's response text.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                usage = response.usage
                if usage and self._token_tracker is not None:
                    await self._record_tokens(
                        model=model,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    )
                content = response.choices[0].message.content or ""
                return content
            except (APIConnectionError, APIStatusError) as exc:
                logger.warning(
                    "LLM request attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_BACKOFF_BASE ** (attempt - 1))
                else:
                    raise RuntimeError(
                        f"LLM chat failed after {_MAX_RETRIES} attempts: {exc}"
                    ) from exc
        # Unreachable, but satisfies type checkers
        raise RuntimeError("LLM chat failed")  # pragma: no cover

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        model: str,
        response_model: type[BaseModel],
        temperature: float = 0.1,
    ) -> BaseModel:
        """Send a chat request and parse the response as a Pydantic model.

        Args:
            messages: List of OpenAI-format message dicts.
            model: Model name to use.
            response_model: Pydantic model class to parse into.
            temperature: Sampling temperature.

        Returns:
            An instance of ``response_model``.

        Raises:
            RuntimeError: If the response cannot be parsed after retries.
        """
        import json
        import re

        raw = await self.chat(
            messages=messages, model=model, temperature=temperature
        )
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        json_str = match.group(1) if match else raw.strip()
        data = json.loads(json_str)
        return response_model.model_validate(data)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """Stream a chat response token by token.

        Args:
            messages: List of OpenAI-format message dicts.
            model: Model name to use.
            temperature: Sampling temperature.

        Yields:
            String chunks from the LLM response.

        Raises:
            RuntimeError: If the stream cannot be established.
        """
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except (APIConnectionError, APIStatusError) as exc:
            raise RuntimeError(f"LLM stream failed: {exc}") from exc

    async def _record_tokens(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        """Record token usage with the tracker if available.

        Args:
            model: Model name.
            prompt_tokens: Number of prompt tokens used.
            completion_tokens: Number of completion tokens generated.
        """
        if self._token_tracker is not None and self._session_id is not None:
            try:
                await self._token_tracker.record(  # type: ignore[attr-defined]
                    session_id=self._session_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            except Exception as exc:
                logger.warning("Token tracking failed: %s", exc)
