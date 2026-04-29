"""Tree-sitter + ChromaDB codebase indexer (DeepWiki light)."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "codebase"
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Supported language file extensions
_LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


class CodebaseIndex:
    """Index a repository's source code for semantic search.

    Uses tree-sitter to parse source files into semantic chunks
    (function/class definitions), embeds them with sentence-transformers,
    and stores them in ChromaDB.
    """

    def __init__(self, chroma_path: str = "./data/chroma") -> None:
        """Initialise the index.

        Args:
            chroma_path: Directory for ChromaDB persistence.
        """
        self._chroma_path = chroma_path
        self._collection: object | None = None
        self._embedder: object | None = None

    def _ensure_collection(self) -> object:
        """Lazily create or retrieve the ChromaDB collection.

        Returns:
            The ChromaDB collection, or None if unavailable.
        """
        if self._collection is not None:
            return self._collection
        try:
            import chromadb

            client = chromadb.PersistentClient(path=self._chroma_path)
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            logger.warning("ChromaDB init failed: %s", exc)
            self._collection = None
        return self._collection  # type: ignore[return-value]

    def _ensure_embedder(self) -> object:
        """Lazily load the sentence-transformers embedding model.

        Returns:
            The SentenceTransformer model, or None if unavailable.
        """
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(_EMBEDDING_MODEL)
        except Exception as exc:
            logger.warning("SentenceTransformer not available: %s", exc)
            self._embedder = None
        return self._embedder  # type: ignore[return-value]

    def index_repo(self, repo_path: str) -> int:
        """Index all supported source files in a repository.

        Args:
            repo_path: Filesystem path to the repository root.

        Returns:
            Number of chunks indexed.
        """
        root = Path(repo_path)
        chunks: list[dict[str, object]] = []

        for ext, lang in _LANG_MAP.items():
            for path in root.rglob(f"*{ext}"):
                if any(part.startswith(".") for part in path.parts):
                    continue  # Skip hidden directories
                file_chunks = self._parse_file(path, lang)
                chunks.extend(file_chunks)

        if not chunks:
            logger.info("No source files found in %s", repo_path)
            return 0

        self._upsert_chunks(chunks)
        logger.info("Indexed %d chunks from %s", len(chunks), repo_path)
        return len(chunks)

    def _parse_file(self, path: Path, lang: str) -> list[dict[str, object]]:
        """Parse a single source file into semantic chunks.

        Args:
            path: Path to the source file.
            lang: Language name for tree-sitter.

        Returns:
            List of chunk dictionaries with ``id``, ``text``, ``file``,
            ``name``, and ``type`` keys.
        """
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        chunks: list[dict[str, object]] = []
        try:
            from tree_sitter_languages import get_parser

            parser = get_parser(lang)
            tree = parser.parse(source.encode())

            def_node_types = {
                "function_definition", "method_definition",
                "class_definition", "function_declaration",
                "class_declaration",
            }

            def walk(node: object) -> None:
                node_type = getattr(node, "type", "")
                if node_type in def_node_types:
                    start = getattr(node, "start_point", (0, 0))
                    end = getattr(node, "end_point", (0, 0))
                    lines = source.splitlines()
                    snippet_lines = lines[start[0] : end[0] + 1]
                    snippet = "\n".join(snippet_lines[:50])  # Max 50 lines per chunk
                    name = _extract_name(node, source)
                    chunk_id = f"{path}::{name}::{start[0]}"
                    chunks.append({
                        "id": chunk_id,
                        "text": snippet,
                        "file": str(path),
                        "name": name,
                        "type": node_type,
                        "line": start[0] + 1,
                    })
                for child in getattr(node, "children", []):
                    walk(child)

            walk(tree.root_node)
        except Exception as exc:
            logger.debug("tree-sitter parse failed for %s: %s", path, exc)
            # Fallback: index the whole file as one chunk
            chunks.append({
                "id": str(path),
                "text": source[:2000],
                "file": str(path),
                "name": path.name,
                "type": "file",
                "line": 1,
            })
        return chunks

    def _upsert_chunks(self, chunks: list[dict[str, object]]) -> None:
        """Embed and upsert chunks into ChromaDB.

        Args:
            chunks: List of chunk dicts produced by ``_parse_file``.
        """
        collection = self._ensure_collection()
        embedder = self._ensure_embedder()
        if collection is None:
            return

        ids = [str(c["id"]) for c in chunks]
        texts = [str(c["text"]) for c in chunks]
        metadatas = [
            {
                "file": str(c["file"]),
                "name": str(c["name"]),
                "type": str(c["type"]),
                "line": int(c.get("line", 1)),
            }
            for c in chunks
        ]

        try:
            if embedder is not None:
                embeddings = embedder.encode(texts).tolist()  # type: ignore[attr-defined]
                collection.upsert(  # type: ignore[attr-defined]
                    ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
                )
            else:
                collection.upsert(  # type: ignore[attr-defined]
                    ids=ids, documents=texts, metadatas=metadatas
                )
        except Exception as exc:
            logger.warning("Chunk upsert failed: %s", exc)

    async def search(self, query: str, n: int = 10) -> list[dict[str, object]]:
        """Search the index for code relevant to a query.

        Args:
            query: Natural language search query.
            n: Maximum number of results to return.

        Returns:
            List of result dicts with ``file``, ``name``, ``snippet``,
            and ``score`` keys.
        """
        collection = self._ensure_collection()
        if collection is None:
            return []
        try:
            results = collection.query(  # type: ignore[attr-defined]
                query_texts=[query], n_results=min(n, 100)
            )
            output: list[dict[str, object]] = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, distances):
                output.append({
                    "file": meta.get("file", ""),
                    "name": meta.get("name", ""),
                    "snippet": doc[:300],
                    "score": round(1.0 - float(dist), 4),
                })
            return output
        except Exception as exc:
            logger.warning("Codebase search failed: %s", exc)
            return []

    def get_file_summary(self, path: str) -> str:
        """Return a brief summary of a file's indexed chunks.

        Args:
            path: File path to summarise.

        Returns:
            Multi-line string listing the function/class names found.
        """
        collection = self._ensure_collection()
        if collection is None:
            return f"(index unavailable for {path})"
        try:
            results = collection.get(  # type: ignore[attr-defined]
                where={"file": path}
            )
            names = [m.get("name", "?") for m in results.get("metadatas", [])]
            if not names:
                return f"(no indexed symbols for {path})"
            return "\n".join(f"  • {n}" for n in names)
        except Exception as exc:
            logger.warning("File summary failed: %s", exc)
            return str(exc)


def _extract_name(node: object, source: str) -> str:
    """Extract the identifier name from a tree-sitter node.

    Args:
        node: A tree-sitter node.
        source: The full source file as a string.

    Returns:
        The node's name, or ``"<anonymous>"``.
    """
    for child in getattr(node, "children", []):
        if getattr(child, "type", "") in ("identifier", "property_identifier"):
            start = getattr(child, "start_byte", 0)
            end = getattr(child, "end_byte", 0)
            return source.encode()[start:end].decode(errors="replace")
    return "<anonymous>"
