# Copilot Handoff: LocalDevin to Devin-Like Agent Runtime

This folder is a handoff package for a long-running GitHub Copilot coding-agent session.
The intended workflow is:

1. Paste the prompt in `COPILOT_ONE_REQUEST_PROMPT.md` into Copilot.
2. Copilot reads these files in order.
3. Copilot uses subagents explicitly.
4. Copilot implements as much as possible in one premium request.
5. Copilot updates `PROGRESS.md` as it works.

## Reading Order

Copilot should read these files in this order:

1. `COPILOT_ONE_REQUEST_PROMPT.md`
2. `TARGET_ARCHITECTURE.md`
3. `IMPLEMENTATION_PLAN.md`
4. `SUBAGENT_DELEGATION.md`
5. `QUALITY_GATES.md`
6. `PROGRESS.md`

## Goal

Move this project from a CLI-driven MVP into a Devin-like local engineering agent.
The short-term target is not perfect feature parity with Cognition Devin. The target is a
solid local agent runtime with persistent sessions, real ReAct execution, safe tool routing,
knowledge/playbook context, GitHub workflow support, browser automation, and repeatable
quality gates.

## Current Baseline

The repository currently contains:

- Python package `localdevin`
- Typer CLI in `cli/main.py`
- Core planner/executor/replanner/orchestrator in `core/`
- Tool implementations in `tools/`
- SQLite session storage in `memory/session_store.py`
- ChromaDB code index and knowledge base modules in `memory/`
- Review and autofix modules in `review/`
- Session insight modules in `insights/`
- Scheduler, GitHub, and Slack integrations in `integrations/`

The existing tests pass when using a workspace-local pytest temp dir:

```powershell
pytest tests/ -q --basetemp .pytest_tmp
```

The default Windows temp directory may produce permission errors in this environment.

## Known Gaps To Prioritize

- `SearchTool` is not wired into the CLI tool router.
- `--playbook` is accepted by the CLI but is not used.
- Knowledge Base is not fed into planning.
- Token tracking is not connected to `LLMClient` from the CLI assembly path.
- Session status transitions are not persisted to SQLite.
- Executor only performs one tool call per plan step.
- Replanner returns decisions, but execution does not continue from revised plans.
- PR creation treats `ToolResult` as a string and does not push the branch.
- Scheduler registers jobs but does not keep a running process alive.
- Shell safety is blocklist-based and weak.
- Browser tooling is basic HTTP fetch, not an interactive browser automation layer.
- `ruff check .` currently reports unused imports/variables.
- `mypy` is configured but not installed in project dependencies.

## Strategy

Do not start by building a polished UI. First extract a durable runtime:

```text
CLI / Web UI / MCP / Scheduler / Slack
        -> SessionService API
        -> AgentWorker
        -> Sandbox / Tools / Memory / GitHub / Browser
```

The CLI should become a thin client, not the agent runtime itself.

## Non-Goals For The First Long Request

- Do not claim perfect Devin parity.
- Do not build a large frontend before the runtime is reliable.
- Do not introduce a new database server unless SQLite is truly blocking.
- Do not replace all existing modules at once.
- Do not hardcode credentials, tokens, repo names, or user-specific paths.
- Do not make destructive git operations.

## Definition Of Useful Progress

The request is successful if Copilot leaves the repo in a better, tested state with:

- A persistent `SessionService` or equivalent runtime boundary.
- CLI commands using that boundary instead of directly assembling all internals.
- Real multi-turn execution per step.
- Replanning that can continue execution when possible.
- Tool routing that includes search, editor, shell, browser, git, knowledge/playbook context.
- Correct PR creation behavior or a clearly tested partial implementation.
- Passing tests, or documented remaining failures in `PROGRESS.md`.

