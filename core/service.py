"""Session service and runtime factory for LocalDevin."""

from pathlib import Path

from config.settings import Settings
from core.models import ToolType
from core.orchestrator import Orchestrator
from core.session import Session
from insights.session_analyzer import SessionAnalyzer
from integrations.scheduler import Scheduler
from llm.client import LLMClient
from llm.token_tracker import TokenTracker
from memory.codebase_index import CodebaseIndex
from memory.knowledge_base import KnowledgeBase
from memory.playbook_loader import PlaybookLoader
from memory.session_store import SessionStore
from review.auto_fix import AutoFix
from review.pr_reviewer import PRReviewer
from tools.browser_tool import BrowserTool
from tools.editor_tool import EditorTool
from tools.git_tool import GitTool
from tools.router import ToolRouter
from tools.search_tool import SearchTool
from tools.shell_tool import ShellTool


class _SchedulerServiceAdapter:
    """Adapter exposing the run_session interface to the scheduler."""

    def __init__(self, service: "SessionService") -> None:
        """Initialise the scheduler adapter."""
        self._service = service

    async def run_session(
        self, task: str, repo_path: str, playbook: str | None = None
    ) -> Session:
        """Run a scheduled task without interactive approval."""
        return await self._service.run_task(
            task=task,
            repo_path=repo_path,
            playbook=playbook,
            require_approval=False,
        )


class SessionService:
    """Application service for LocalDevin sessions and related commands."""

    def __init__(
        self,
        settings: Settings,
        session_store: SessionStore | None = None,
        token_tracker: TokenTracker | None = None,
        knowledge_base: KnowledgeBase | None = None,
        playbook_loader: PlaybookLoader | None = None,
        codebase_index: CodebaseIndex | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            settings: Runtime settings.
            session_store: Optional session store override.
            token_tracker: Optional token tracker override.
            knowledge_base: Optional knowledge base override.
            playbook_loader: Optional playbook loader override.
            codebase_index: Optional codebase index override.
        """
        self._settings = settings
        self._store = session_store or SessionStore(db_path=settings.db_path)
        self._token_tracker = token_tracker or TokenTracker(
            db_path=settings.db_path,
            max_session_tokens=settings.max_session_tokens,
        )
        self._knowledge_base = knowledge_base or KnowledgeBase(
            knowledge_dir=settings.knowledge_dir,
            chroma_path=settings.chroma_path,
        )
        self._playbook_loader = playbook_loader or PlaybookLoader(
            playbooks_dir=settings.playbooks_dir,
        )
        self._codebase_index = codebase_index or CodebaseIndex(
            chroma_path=settings.chroma_path,
        )

    async def run_task(
        self,
        task: str,
        repo_path: str,
        playbook: str | None = None,
        require_approval: bool = True,
    ) -> Session:
        """Run a full agent task through the runtime service."""
        planning_context, context_metadata = await self._load_planning_context(
            task=task,
            repo_path=repo_path,
            playbook=playbook,
        )
        orchestrator = self._build_orchestrator(repo_path=repo_path)
        return await orchestrator.run_session(
            task=task,
            repo_path=repo_path,
            playbook=playbook,
            planning_context=planning_context,
            context_metadata=context_metadata,
            require_approval=require_approval,
        )

    async def ask_codebase(self, question: str, repo_path: str) -> str:
        """Answer a question about the indexed codebase."""
        results = await self._codebase_index.search(query=question, n=5)
        context = "\n\n".join(
            f"[{result['file']}]\n{result['snippet']}" for result in results
        ) or "(no indexed code found)"
        llm = self._build_llm_client()
        return await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert code assistant. "
                        "Answer the question based on the provided code context."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            model=self._settings.fast_model,
        )

    async def review_repo(self, repo_path: str, branch: str = "") -> object:
        """Review the current branch for a repository."""
        reviewer = PRReviewer(settings=self._settings, llm_client=self._build_llm_client())
        return await reviewer.review(repo_path=repo_path, branch=branch)

    def index_repo(self, repo_path: str) -> int:
        """Index a repository for semantic search."""
        return self._codebase_index.index_repo(repo_path=repo_path)

    async def analyze_session(self, session_id: str) -> object:
        """Generate insights for a session."""
        analyzer = SessionAnalyzer(
            settings=self._settings,
            session_store=self._store,
            llm_client=self._build_llm_client(),
        )
        return await analyzer.analyze(session_id=session_id)

    def list_knowledge(self) -> list[object]:
        """Load all knowledge items."""
        return self._knowledge_base.load_all()

    async def get_recent_sessions(self, limit: int = 10) -> list[dict[str, object]]:
        """Return recent persisted sessions."""
        return await self._store.get_recent_sessions(limit=limit)

    def create_scheduler(self) -> Scheduler:
        """Create a scheduler bound to this service."""
        return Scheduler(
            settings=self._settings,
            orchestrator=_SchedulerServiceAdapter(self),
        )

    def _build_llm_client(self, session_id: str | None = None) -> LLMClient:
        """Create a session-aware LLM client."""
        return LLMClient(
            base_url=f"{self._settings.ollama_base_url}/v1",
            token_tracker=self._token_tracker,
            session_id=session_id,
        )

    def _build_orchestrator(self, repo_path: str) -> Orchestrator:
        """Create an orchestrator instance for a repository."""
        llm_client = self._build_llm_client()
        tool_router = self._build_tool_router(repo_path=repo_path)
        reviewer = PRReviewer(settings=self._settings, llm_client=llm_client)
        auto_fix = AutoFix(settings=self._settings, llm_client=llm_client)
        analyzer = SessionAnalyzer(
            settings=self._settings,
            session_store=self._store,
            llm_client=llm_client,
        )
        return Orchestrator(
            settings=self._settings,
            llm_client=llm_client,
            tool_router=tool_router,
            session_store=self._store,
            pr_reviewer=reviewer,
            auto_fix=auto_fix,
            session_analyzer=analyzer,
            token_tracker=self._token_tracker,
        )

    def _build_tool_router(self, repo_path: str) -> ToolRouter:
        """Create the runtime tool router for a repository."""
        shell_tool = ShellTool(cwd=repo_path)
        editor_tool = EditorTool(sandbox_root=repo_path)
        git_tool = GitTool(
            repo_path=repo_path,
            github_token=self._settings.github_token,
            default_branch=self._settings.github_default_branch,
        )
        browser_tool = BrowserTool()
        search_tool = SearchTool(codebase_index=self._codebase_index)
        return ToolRouter(
            tools={
                ToolType.SHELL: shell_tool,
                ToolType.EDITOR_READ: editor_tool,
                ToolType.EDITOR_WRITE: editor_tool,
                ToolType.GIT: git_tool,
                ToolType.BROWSER: browser_tool,
                ToolType.SEARCH: search_tool,
            },
            named_tools={
                "shell": shell_tool,
                "editor": editor_tool,
                "git": git_tool,
                "browser": browser_tool,
                "search": search_tool,
            },
            session_store=self._store,
        )

    async def _load_planning_context(
        self,
        task: str,
        repo_path: str,
        playbook: str | None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Load planning context from playbooks, knowledge, and search."""
        context: dict[str, object] = {}
        metadata: dict[str, object] = {"repo_path": repo_path}

        if playbook:
            playbook_content = self._playbook_loader.load(playbook)
            context["playbook"] = playbook_content
            metadata["playbook"] = playbook

        knowledge_items = self._knowledge_base.get_relevant(
            task=task,
            repo=Path(repo_path).name,
        )
        if knowledge_items:
            context["knowledge"] = "\n\n".join(
                f"### {item.name}\n{item.content}" for item in knowledge_items
            )
            metadata["knowledge_items"] = [item.name for item in knowledge_items]

        search_results = await self._codebase_index.search(query=task, n=3)
        if search_results:
            context["search_results"] = "\n\n".join(
                f"[{result['file']}]\n{result['snippet']}" for result in search_results
            )
            metadata["search_results"] = [result["file"] for result in search_results]

        return context, metadata


def build_session_service(settings: Settings | None = None) -> SessionService:
    """Build a reusable session service."""
    return SessionService(settings=settings or Settings())
