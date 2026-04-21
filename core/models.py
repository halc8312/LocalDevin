"""Pydantic data models for LocalDevin."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class StepSize(str, Enum):
    """Estimated size of a plan step."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class SessionStatus(str, Enum):
    """Lifecycle status of a LocalDevin session."""

    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class ToolType(str, Enum):
    """Available tool types for agent actions."""

    SHELL = "shell"
    EDITOR_READ = "editor_read"
    EDITOR_WRITE = "editor_write"
    BROWSER = "browser"
    SEARCH = "search"
    GIT = "git"


class ReplanDecision(str, Enum):
    """Decision options when replanning after an error."""

    INVESTIGATE = "investigate"
    FIX = "fix"
    SKIP_AND_LOG = "skip_and_log"
    ESCALATE = "escalate"


class PlanStep(BaseModel):
    """A single step in an execution plan.

    Attributes:
        id: Unique step identifier (e.g. ``step_1``).
        description: Human-readable description of the step.
        depends_on: IDs of steps that must complete before this one.
        tools: Tools required to execute this step.
        size: Estimated effort size.
        status: Current execution status of this step.
    """

    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    tools: list[ToolType]
    size: StepSize
    status: SessionStatus = SessionStatus.PENDING


class Plan(BaseModel):
    """A complete execution plan produced by the Planner.

    Attributes:
        task_summary: Short summary of the task.
        completion_criteria: List of criteria that define task completion.
        steps: Ordered list of plan steps (may form a DAG via ``depends_on``).
    """

    task_summary: str
    completion_criteria: list[str]
    steps: list[PlanStep]


class ToolCall(BaseModel):
    """Represents a tool invocation requested by the LLM.

    Attributes:
        tool: The tool to call.
        args: Keyword arguments for the tool.
    """

    tool: ToolType
    args: dict[str, object]


class ToolResult(BaseModel):
    """Structured result from a tool execution.

    Attributes:
        success: Whether the tool completed successfully.
        output: Tool stdout / result string.
        error: Error message if the tool failed.
        suggestions: Optional hints to resolve the error.
    """

    success: bool
    output: str
    error: str | None = None
    suggestions: list[str] = Field(default_factory=list)


class ReActStep(BaseModel):
    """One iteration of the ReAct (Reason-Act-Observe) loop.

    Attributes:
        step_id: ID of the plan step this belongs to.
        think: The reasoning text before acting.
        act: The tool call decided upon.
        observe: The observation after executing the tool.
        next_action: Description of what should happen next.
        timestamp: When this step was executed.
        tokens_used: Number of tokens consumed in this step.
    """

    step_id: str
    think: str
    act: ToolCall
    observe: str
    next_action: str
    timestamp: datetime = Field(default_factory=datetime.now)
    tokens_used: int = 0


class ReplanAction(BaseModel):
    """Decision and revised plan produced by the Replanner.

    Attributes:
        original_step: ID of the step that failed.
        error: The error message that triggered replanning.
        decision: The replanning decision.
        reasoning: Explanation of the decision.
        revised_steps: New/replacement steps to insert into the plan.
    """

    original_step: str
    error: str
    decision: ReplanDecision
    reasoning: str
    revised_steps: list[PlanStep] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    """A single issue found during PR review.

    Attributes:
        category: Severity category.
        file: Source file path.
        line: Line number (optional).
        description: Description of the issue.
        suggestion: Suggested fix.
    """

    category: str
    file: str
    line: int | None = None
    description: str
    suggestion: str


class ReviewResult(BaseModel):
    """Result of a PR review.

    Attributes:
        summary: Overall review summary.
        issues: List of detected issues.
        approved: Whether the PR is approved.
    """

    summary: str
    issues: list[ReviewIssue] = Field(default_factory=list)
    approved: bool = False


class SessionInsight(BaseModel):
    """Analytics produced for a completed session.

    Attributes:
        session_id: The session that was analysed.
        total_tokens: Total tokens consumed.
        user_messages: Number of user-initiated messages.
        session_size: Bucketed size label (XS/S/M/L/XL).
        category: Task category (e.g. Bug Fixing).
        issues: Detected issues in the session.
        improved_prompt: Suggested improved prompt.
        knowledge_suggestions: Candidate Knowledge items to create.
    """

    session_id: str
    total_tokens: int
    user_messages: int
    session_size: str
    category: str
    issues: list[dict[str, object]]
    improved_prompt: str
    knowledge_suggestions: list[str]


class KnowledgeItem(BaseModel):
    """A Knowledge Base entry.

    Attributes:
        name: Short identifier for the knowledge item.
        trigger: Natural language trigger description.
        content: The knowledge content in Markdown.
        repos: Repository slugs this knowledge applies to.
        enabled: Whether this item is active.
    """

    name: str
    trigger: str
    content: str
    repos: list[str] = Field(default_factory=lambda: ["all"])
    enabled: bool = True
