"""Slack notification bridge using slack-bolt."""

import logging

from config.settings import Settings

logger = logging.getLogger(__name__)


class SlackBridge:
    """Send notifications to a Slack channel via the Slack Bolt SDK.

    All methods gracefully no-op when Slack credentials are not configured.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the bridge.

        Args:
            settings: Application settings.
        """
        self._settings = settings
        self._app: object | None = None

    def _get_app(self) -> object | None:
        """Lazily initialise the Slack Bolt app.

        Returns:
            A ``slack_bolt.App`` instance, or None if credentials are missing.
        """
        if self._app is not None:
            return self._app
        if not self._settings.slack_bot_token:
            return None
        try:
            from slack_bolt import App

            self._app = App(
                token=self._settings.slack_bot_token,
                signing_secret=self._settings.slack_signing_secret or "dummy",
            )
        except Exception as exc:
            logger.warning("Slack init failed: %s", exc)
            self._app = None
        return self._app

    def send(self, message: str, channel: str | None = None) -> bool:
        """Send a plain-text message to a Slack channel.

        Args:
            message: The message text.
            channel: Channel to post to (defaults to ``settings.slack_channel``).

        Returns:
            True if the message was sent successfully, False otherwise.
        """
        app = self._get_app()
        if app is None:
            logger.debug("Slack not configured – skipping notification")
            return False

        channel = channel or self._settings.slack_channel
        if not channel:
            logger.debug("No Slack channel configured – skipping notification")
            return False

        try:
            app.client.chat_postMessage(channel=channel, text=message)  # type: ignore[attr-defined]
            return True
        except Exception as exc:
            logger.warning("Slack send failed: %s", exc)
            return False

    def notify_session_completed(
        self,
        session_id: str,
        task: str,
        tokens: int,
        pr_url: str | None = None,
    ) -> None:
        """Send a session-completed notification.

        Args:
            session_id: Session identifier.
            task: Task description.
            tokens: Total tokens consumed.
            pr_url: Optional PR URL.
        """
        pr_text = f"\nPR: {pr_url}" if pr_url else ""
        message = (
            f"✅ LocalDevin session completed\n"
            f"Task: {task}\n"
            f"Session: `{session_id[:8]}`\n"
            f"Tokens: {tokens:,}{pr_text}"
        )
        self.send(message)

    def notify_session_failed(
        self, session_id: str, task: str, error: str
    ) -> None:
        """Send a session-failed notification.

        Args:
            session_id: Session identifier.
            task: Task description.
            error: Error message.
        """
        message = (
            f"❌ LocalDevin session failed\n"
            f"Task: {task}\n"
            f"Session: `{session_id[:8]}`\n"
            f"Error: {error[:200]}"
        )
        self.send(message)
