# Subagent Delegation Instructions

Copilot must use subagents explicitly when the environment supports them. This is
important because the work is too broad for a single linear pass.

## General Rules For Subagents

- Subagents are not alone in the codebase.
- Each subagent must respect work done by other agents.
- Each subagent must not revert unrelated changes.
- Each subagent must list files changed in its final report.
- Each subagent must run relevant tests for its area when feasible.
- Assign disjoint write ownership to avoid conflicts.
- If a subagent discovers it needs to edit files outside its ownership, it should report that instead of editing them.

## Recommended Subagents

### Subagent 1: Runtime Explorer

Type: explorer

Purpose:

- Inspect current runtime assembly.
- Identify exact call paths from CLI to Orchestrator to Executor.
- Report where to insert `SessionService` and `ToolRouter`.

Read ownership:

- `cli/main.py`
- `core/orchestrator.py`
- `core/executor.py`
- `core/planner.py`
- `core/replanner.py`
- `memory/session_store.py`
- `llm/client.py`

Write ownership:

- None, unless explicitly promoted to worker.

Prompt:

```text
Inspect the current LocalDevin runtime wiring. Identify exactly where CLI directly assembles runtime dependencies, where session state is not persisted, and where tool routing should be extracted. Do not edit files. Return a concise implementation map with file/function references and risks.
```

### Subagent 2: Quality And Test Worker

Type: worker

Purpose:

- Fix ruff failures.
- Add missing test/dev dependency handling if appropriate.
- Keep tests green while other work proceeds.

Write ownership:

- `pyproject.toml`
- `tests/`
- small unused import cleanup in touched modules
- `docs/copilot-devin-parity/PROGRESS.md`

Do not edit:

- runtime architecture files unless coordinating with main agent
- `core/service.py`
- `tools/router.py`

Prompt:

```text
You are responsible for quality cleanup and tests. Fix current ruff failures without changing behavior. Ensure `pytest tests/ -q --basetemp .pytest_tmp` passes. If adding mypy/dev dependency support, do it minimally and document commands. You are not alone in the codebase; do not revert changes by others. List all files changed and commands run.
```

### Subagent 3: Runtime Extraction Worker

Type: worker

Purpose:

- Add `SessionService`.
- Move runtime assembly out of CLI.
- Persist session status transitions.

Write ownership:

- `core/service.py`
- `core/orchestrator.py`
- `cli/main.py`
- `memory/session_store.py`
- tests specifically for service/session persistence

Do not edit:

- `tools/router.py` unless coordinating with Tool Context Worker
- GitHub-specific implementation

Prompt:

```text
Implement a SessionService boundary for LocalDevin. Move runtime assembly out of cli/main.py and make CLI commands call the service. Persist session status transitions through SessionStore. Preserve existing CLI behavior. You are not alone in the codebase; do not revert changes by others. Keep edits scoped to service/runtime/session files and tests. Run relevant tests and list files changed.
```

### Subagent 4: Tool Context Worker

Type: worker

Purpose:

- Implement `ToolRouter`.
- Wire `SearchTool`.
- Connect playbook and knowledge context to planning.

Write ownership:

- `tools/router.py`
- `tools/search_tool.py`
- `memory/knowledge_base.py`
- `memory/playbook_loader.py` if added
- `core/planner.py`
- context-related tests

Do not edit:

- CLI broadly, except small integration hooks coordinated with Runtime Extraction Worker
- GitHub PR workflow

Prompt:

```text
Implement a real ToolRouter and context loading path. Wire ToolType.SEARCH to SearchTool. Add playbook loading from the playbooks directory and pass selected playbook plus relevant KnowledgeBase content into Planner.create_plan context. Preserve existing APIs where possible. You are not alone in the codebase; do not revert changes by others. Add tests for routing and context loading. List files changed and commands run.
```

### Subagent 5: Agent Loop Worker

Type: worker

Purpose:

- Make Executor multi-turn.
- Add done/continue/fail/needs_input semantics.
- Make Replanner continuation possible.

Write ownership:

- `core/executor.py`
- `core/replanner.py`
- `core/models.py`
- `config/prompts/execution_system.md`
- `config/prompts/replan_system.md`
- executor/replanner tests

Do not edit:

- CLI/service assembly unless coordinated
- GitHub tool

Prompt:

```text
Upgrade Executor from one tool call per step into a bounded multi-turn ReAct loop. Feed observations back into the model. Add structured status semantics: continue, done, failed, needs_input. Modify replanning so FIX/SKIP/ESCALATE decisions can change execution flow where feasible. You are not alone in the codebase; do not revert changes by others. Add focused tests for multi-iteration execution and replanning continuation. List files changed and commands run.
```

### Subagent 6: GitHub Scheduler Worker

Type: worker

Purpose:

- Fix GitTool PR workflow.
- Add push behavior.
- Improve scheduler command/process behavior.

Write ownership:

- `tools/git_tool.py`
- `integrations/scheduler.py`
- scheduler/git tests
- limited CLI changes for scheduler command if coordinated

Do not edit:

- executor/replanner internals
- knowledge/playbook internals

Prompt:

```text
Fix GitHub and scheduler behavior. GitTool should handle create branch, commit, push branch, and create PR with consistent ToolResult handling. Support common GitHub remote URL formats. Scheduler should have a way to run as a long-lived process and invoke SessionService or an injected orchestrator cleanly. You are not alone in the codebase; do not revert changes by others. Use mocks/temp repos for tests. List files changed and commands run.
```

## Conflict Handling

If two subagents need the same file:

1. Main agent decides ownership.
2. One subagent reports intended changes but does not edit.
3. Main agent integrates manually.
4. Tests are run after integration.

## Subagent Completion Report Template

Each subagent should report:

```text
Scope:
Files changed:
Commands run:
Tests passed:
Tests failed:
Remaining risks:
Needed follow-up:
```

