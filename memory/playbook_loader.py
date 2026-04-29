"""Playbook discovery and loading for planner context."""

from pathlib import Path


class PlaybookLoader:
    """Load Markdown playbooks from the configured playbooks directory."""

    def __init__(self, playbooks_dir: str = "./playbooks") -> None:
        """Initialise the loader.

        Args:
            playbooks_dir: Directory containing Markdown playbooks.
        """
        self._playbooks_dir = Path(playbooks_dir)

    def load(self, name: str) -> str:
        """Load a playbook by name.

        Args:
            name: Playbook name with or without the ``.md`` suffix.

        Returns:
            Playbook Markdown content.

        Raises:
            ValueError: If the playbook does not exist.
        """
        filename = name if name.endswith(".md") else f"{name}.md"
        path = self._playbooks_dir / filename
        if not path.exists():
            raise ValueError(
                f"Playbook '{name}' not found in '{self._playbooks_dir}'."
            )
        return path.read_text(encoding="utf-8")

    def list_playbooks(self) -> list[str]:
        """Return the available playbook names."""
        if not self._playbooks_dir.exists():
            return []
        return sorted(path.stem for path in self._playbooks_dir.glob("*.md"))
