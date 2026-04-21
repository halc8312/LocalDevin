"""Knowledge Base management backed by Markdown files + ChromaDB."""

import logging
from pathlib import Path

import yaml

from core.models import KnowledgeItem

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "knowledge_base"


class KnowledgeBase:
    """Manage Knowledge Base entries stored as Markdown files.

    Each Markdown file in the ``knowledge_dir`` is treated as one knowledge
    item.  ChromaDB is used for semantic retrieval against trigger queries.
    """

    def __init__(
        self,
        knowledge_dir: str = "./knowledge",
        chroma_path: str = "./data/chroma",
    ) -> None:
        """Initialise the Knowledge Base.

        Args:
            knowledge_dir: Directory containing Markdown knowledge files.
            chroma_path: Path for ChromaDB persistence.
        """
        self._knowledge_dir = Path(knowledge_dir)
        self._chroma_path = chroma_path
        self._items: list[KnowledgeItem] = []
        self._collection: object | None = None

    def _ensure_collection(self) -> object:
        """Lazily create or retrieve the ChromaDB collection.

        Returns:
            The ChromaDB collection object.
        """
        if self._collection is not None:
            return self._collection
        try:
            import chromadb

            client = chromadb.PersistentClient(path=self._chroma_path)
            self._collection = client.get_or_create_collection(_COLLECTION_NAME)
        except Exception as exc:
            logger.warning("ChromaDB unavailable for knowledge base: %s", exc)
            self._collection = None
        return self._collection  # type: ignore[return-value]

    def load_all(self) -> list[KnowledgeItem]:
        """Load all Markdown knowledge files from the knowledge directory.

        Returns:
            List of KnowledgeItem instances.
        """
        self._items = []
        if not self._knowledge_dir.exists():
            logger.info("Knowledge directory '%s' not found", self._knowledge_dir)
            return self._items

        triggers_path = self._knowledge_dir / "triggers.yaml"
        trigger_map: dict[str, str] = {}
        if triggers_path.exists():
            raw = yaml.safe_load(triggers_path.read_text(encoding="utf-8")) or {}
            trigger_map = raw.get("triggers", {})

        for md_file in sorted(self._knowledge_dir.glob("*.md")):
            name = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            trigger = trigger_map.get(name, name.replace("-", " "))
            self._items.append(
                KnowledgeItem(name=name, trigger=trigger, content=content)
            )

        self._index_items()
        logger.info("Loaded %d knowledge items", len(self._items))
        return self._items

    def _index_items(self) -> None:
        """Index knowledge items in ChromaDB for semantic retrieval."""
        collection = self._ensure_collection()
        if collection is None or not self._items:
            return
        try:
            collection.upsert(  # type: ignore[attr-defined]
                ids=[item.name for item in self._items],
                documents=[item.trigger for item in self._items],
                metadatas=[{"name": item.name, "repos": ",".join(item.repos)} for item in self._items],
            )
        except Exception as exc:
            logger.warning("Knowledge indexing failed: %s", exc)

    def get_relevant(self, task: str, repo: str = "all") -> list[KnowledgeItem]:
        """Return knowledge items relevant to the given task and repo.

        Args:
            task: Task description to match against.
            repo: Repository slug (or ``"all"``).

        Returns:
            List of relevant KnowledgeItem instances.
        """
        if not self._items:
            self.load_all()

        collection = self._ensure_collection()
        if collection is None:
            return self._items[:3]  # Fallback: return first 3 items

        try:
            results = collection.query(  # type: ignore[attr-defined]
                query_texts=[task], n_results=min(5, len(self._items))
            )
            matched_ids: list[str] = results["ids"][0]
            item_map = {item.name: item for item in self._items}
            matched = [item_map[mid] for mid in matched_ids if mid in item_map]
            # Filter by repo
            filtered = [
                item for item in matched
                if "all" in item.repos or repo in item.repos
            ]
            return filtered
        except Exception as exc:
            logger.warning("Knowledge retrieval failed: %s", exc)
            return []

    def suggest_new(self, session_history: list[dict[str, object]]) -> list[str]:
        """Generate new knowledge suggestions from session history.

        Args:
            session_history: List of event dicts from a completed session.

        Returns:
            List of suggested knowledge item descriptions.
        """
        suggestions: list[str] = []
        for event in session_history:
            if event.get("event_type") == "step_failed":
                data = event.get("data", {})
                error = data.get("error", "") if isinstance(data, dict) else ""
                if error:
                    suggestions.append(
                        f"How to handle: {str(error)[:100]}"
                    )
        return list(dict.fromkeys(suggestions))[:5]  # Deduplicate, max 5
