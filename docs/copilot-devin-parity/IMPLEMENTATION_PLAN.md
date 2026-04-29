# Implementation Plan

This plan is ordered for a single long-running Copilot request. The agent should
complete phases in order, but it may use subagents to run independent phases in
parallel. Prefer completing a tested vertical slice over partially rewriting many modules.

## Phase 0: Baseline And Quality Cleanup

### Tasks

- Run:

```powershell
pytest tests/ -q --basetemp .pytest_tmp
ruff check .
```

- Fix current ruff failures:
  - unused `Path` in `cli/main.py`
  - unused `history` in `core/orchestrator.py`
  - unused `asyncio` in `integrations/scheduler.py`
  - unused `language` in `memory/codebase_index.py`
  - unused imports in tests and tools
- Decide how to expose mypy:
  - either add `mypy` to a dev dependency group, or
  - document that typecheck is optional until packaging supports dev extras.

### Acceptance Criteria

- `ruff check .` passes.
- `pytest tests/ -q --basetemp .pytest_tmp` passes.
- No behavioral refactor yet.

## Phase 1: Extract SessionService

### Goal

Move runtime assembly out of `cli/main.py` into an application service that can be used
by CLI, scheduler, future web UI, and future MCP.

### Suggested Files

Add:

- `core/service.py`
- `tools/router.py`
- possibly `core/runtime.py` or `core/factory.py`

Modify:

- `cli/main.py`
- `core/orchestrator.py`
- `memory/session_store.py`
- tests under `tests/`

### Tasks

- Create a `SessionService` that owns:
  - settings
  - llm client
  - token tracker
  - session store
  - tool router
  - orchestrator
  - reviewer/autofix/analyzer where appropriate
- Create a factory function such as:

```python
def build_session_service(settings: Settings | None = None) -> SessionService:
    ...
```

- CLI command `run` should call the service:

```python
await service.run_task(task=task, repo_path=repo, playbook=playbook)
```

- CLI command `review`, `index`, `insights`, `status`, and `schedule` may be moved gradually.
- Persist status changes through `SessionStore.update_status`.
- Persist final token count to `sessions.total_tokens` or add a method to do so.

### Acceptance Criteria

- CLI no longer contains a nested `_SimpleToolRouter`.
- Existing CLI behavior remains available.
- Tests cover service construction and at least one mocked run.
- Session status updates are stored.

## Phase 2: ToolRouter, SearchTool, Knowledge, And Playbooks

### Goal

Make context and tools available to the planner/executor in a coherent way.

### Suggested Files

Add:

- `tools/router.py`
- `memory/playbook_loader.py` or reuse `memory/skill_loader.py` if appropriate

Modify:

- `cli/main.py`
- `core/planner.py`
- `core/orchestrator.py`
- `core/service.py`
- `tools/search_tool.py`
- `memory/knowledge_base.py`
- tests

### Tasks

- Implement a real `ToolRouter`:
  - route `ToolType.SHELL`
  - route `ToolType.EDITOR_READ`
  - route `ToolType.EDITOR_WRITE`
  - route `ToolType.GIT`
  - route `ToolType.BROWSER`
  - route `ToolType.SEARCH`
- Ensure editor read/write actions are explicit and tested.
- Add playbook loading:
  - `--playbook test-coverage` should load `playbooks/test-coverage.md`
  - invalid playbook should produce a clear error
- Load relevant knowledge:
  - call `KnowledgeBase.get_relevant(task, repo=...)`
  - pass matched content into `Planner.create_plan(..., context=...)`
- Optionally run a codebase search before planning if an index exists.
- Record which knowledge/playbook items were used as session events.

### Acceptance Criteria

- `SearchTool` can be used by Executor.
- `localdevin run ... --playbook name` changes planner context.
- Knowledge usage is observable in session events.
- Tests cover playbook loading and search routing.

## Phase 3: Multi-Turn ReAct Executor

### Goal

Make execution actually agentic within each plan step.

### Suggested Files

Modify:

- `core/executor.py`
- `config/prompts/execution_system.md`
- `core/models.py`
- tests

### Tasks

- Add max iterations per step, for example `max_step_iterations`.
- Update ReAct JSON schema to include a status:

```json
{
  "think": "...",
  "act": {"tool": "shell", "args": {"command": "pytest -q"}},
  "observe": "",
  "next": "continue",
  "status": "continue"
}
```

Valid statuses:

- `continue`
- `done`
- `failed`
- `needs_input`

- Feed tool results back into the next model call.
- Store every tool iteration, not just one `ReActStep`.
- Mark the plan step completed only when status is `done` and the last tool result succeeded.
- If max iterations are exceeded, fail the step and trigger replanning.
- Preserve compatibility with existing tests or update them to the stronger behavior.

### Acceptance Criteria

- A single plan step can perform multiple tool calls.
- Observations influence later calls.
- Tests cover:
  - one-step success
  - multi-iteration success
  - failed tool call
  - max iteration failure
  - malformed model JSON retry

## Phase 4: Replanning That Continues

### Goal

Make replanning affect execution rather than just logging a decision before failure.

### Suggested Files

Modify:

- `core/replanner.py`
- `core/executor.py`
- `core/orchestrator.py`
- `core/models.py`
- tests

### Tasks

- Return a structured action from `on_error`.
- Let Executor apply the action:
  - insert diagnostic steps
  - replace failed step
  - skip and continue
  - escalate and stop
- Validate revised step dependencies after insertion.
- Persist replan decisions as events.
- Avoid infinite replan loops.

### Acceptance Criteria

- If Replanner returns `FIX` with revised steps, execution can continue.
- If Replanner returns `SKIP_AND_LOG`, dependent steps are handled safely.
- If Replanner returns `ESCALATE`, session status is persisted as escalated.
- Tests cover each decision type.

## Phase 5: GitHub And PR Workflow

### Goal

Make branch, commit, push, PR, review, and autofix flows reliable enough for real use.

### Suggested Files

Modify:

- `tools/git_tool.py`
- `core/orchestrator.py` or `core/service.py`
- `review/pr_reviewer.py`
- tests

### Tasks

- Make `GitTool.create_pr` return `ToolResult` consistently and callers inspect it.
- Add `push_branch`.
- Handle remote URL formats:
  - `https://github.com/owner/repo.git`
  - `git@github.com:owner/repo.git`
  - enterprise GitHub domains when possible
- If no remote exists, return a clear error.
- If nothing to commit, do not try to create a PR unless explicitly configured.
- Review diff against the correct base.
- Add tests with mocked GitHub API and temp git repo.

### Acceptance Criteria

- PR creation path does not treat a `ToolResult` as a raw string.
- Branch push happens before PR creation.
- Remote slug parsing is tested.
- No token configured means PR creation is skipped cleanly.

## Phase 6: Scheduler And Long-Running Process

### Goal

Make scheduled sessions real.

### Suggested Files

Modify:

- `cli/main.py`
- `integrations/scheduler.py`
- possibly `core/service.py`
- tests

### Tasks

- Add one of:
  - `localdevin scheduler run`
  - `localdevin schedule --run`
  - `localdevin daemon`
- Keep the process alive.
- Persist jobs where feasible.
- Add graceful shutdown.
- Ensure scheduled sessions use `SessionService`.
- Add rate-limited failure logging/notification if simple.

### Acceptance Criteria

- User can register and run a scheduler process.
- Scheduler does not discard jobs immediately because the process exits.
- Tests cover job registration and service invocation with mocks.

## Phase 7: Browser Automation

### Goal

Move from simple HTTP fetch toward a real browser tool while preserving a lightweight fallback.

### Suggested Files

Add:

- `tools/playwright_browser_tool.py`

Modify:

- `tools/router.py`
- `pyproject.toml`
- tests

### Tasks

- Add optional Playwright browser tool if dependency strategy is acceptable.
- Support:
  - navigate
  - click
  - type
  - screenshot
  - text snapshot
  - wait for selector
- Keep current `BrowserTool` as HTTP fetch fallback.
- Do not make browser automation a hard dependency unless tests remain reliable.

### Acceptance Criteria

- Browser tool supports at least navigate and text/screenshot extraction.
- Tests are mocked or skipped cleanly if Playwright is unavailable.

## Phase 8: Insights, Evaluation, And Documentation

### Goal

Make progress measurable.

### Tasks

- Improve `SessionAnalyzer` to use token tracker data and session events.
- Add action items:
  - missing dependency
  - failing tests
  - repeated command failure
  - missing token/secret
- Add a simple eval harness:
  - run small tasks against fixture repos
  - measure pass/fail
  - record runtime, token count, retries
- Update root `README.md` with accurate setup/run/test behavior.

### Acceptance Criteria

- Session insights reflect real stored events and token usage.
- Docs do not claim unimplemented behavior.
- A developer can run tests and understand current limitations.

