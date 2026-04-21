"""Prompt improvement suggestions based on session analysis."""

import logging

from config.settings import Settings

logger = logging.getLogger(__name__)


class PromptImprover:
    """Generate improved prompts based on patterns observed across sessions."""

    def __init__(self, settings: Settings, llm_client: object) -> None:
        """Initialise the improver.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
        """
        self._settings = settings
        self._llm = llm_client

    async def suggest(
        self,
        original_prompt: str,
        session_history: list[dict[str, object]],
    ) -> str:
        """Generate an improved version of the original prompt.

        Args:
            original_prompt: The task prompt used in the session.
            session_history: Events from the completed session.

        Returns:
            An improved prompt string.
        """
        failed_steps = [
            e for e in session_history if e.get("event_type") == "step_failed"
        ]
        failure_summary = "\n".join(
            str(e.get("data", {}).get("error", "unknown"))[:80]
            for e in failed_steps[:5]
        ) or "No failures."

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a prompt engineering expert specialising in AI coding agents. "
                    "Improve the given task prompt to be more specific, unambiguous, and "
                    "likely to succeed on first attempt."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original prompt:\n{original_prompt}\n\n"
                    f"Execution issues encountered:\n{failure_summary}\n\n"
                    "Provide an improved prompt:"
                ),
            },
        ]

        try:
            return await self._llm.chat(  # type: ignore[attr-defined]
                messages=messages,
                model=self._settings.fast_model,
                temperature=0.3,
            )
        except Exception as exc:
            logger.warning("Prompt suggestion failed: %s", exc)
            return original_prompt
