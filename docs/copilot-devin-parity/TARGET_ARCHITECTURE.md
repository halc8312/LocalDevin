# Target Architecture

## Current Shape

The project currently behaves like this:

```text
Typer CLI
  -> builds Settings, LLMClient, SessionStore, tools, reviewer, autofix
  -> Orchestrator
  -> Planner
  -> Executor
  -> Tools
```

This is acceptable for an MVP, but it does not support durable sessions, multiple clients,
resume, rich progress views, scheduling, external API control, or reliable long-running work.

## Desired Shape

Move toward this structure:

```text
Clients:
  - CLI
  - future Web UI
  - future MCP server
  - Scheduler
  - Slack/GitHub webhooks

Application layer:
  - SessionService
  - SessionRepository / SessionStore
  - EventStore
  - RuntimeConfig

Agent runtime:
  - AgentWorker
  - Planner
  - Executor
  - Replanner
  - ToolRouter
  - TokenTracker
  - SessionAnalyzer

Context:
  - CodebaseIndex
  - KnowledgeBase
  - PlaybookLoader
  - repo summaries
  - prior session learnings

Tools:
  - ShellTool
  - EditorTool
  - SearchTool
  - BrowserTool / PlaywrightBrowserTool
  - GitTool
  - future MCP tools

Execution environment:
  - local repo checkout
  - future Docker/WSL sandbox
  - command logs
  - file diffs
  - browser artifacts
```

## Runtime Principles

### CLI Is A Client

The CLI should not directly assemble the entire runtime. It should call a service:

```python
service = build_session_service(settings)
session = await service.run_task(task=task, repo_path=repo, playbook=playbook)
```

This allows the same service to be reused by scheduler, web UI, MCP, and tests.

### Sessions Are Durable

Every state transition should be persisted:

- pending
- planning
- awaiting_approval
- executing
- replanning
- completed
- failed
- escalated

Every meaningful event should be persisted:

- prompt received
- context loaded
- plan created
- plan approved/rejected
- tool call started
- tool call completed/failed
- file changed
- command executed
- replanning decision
- review issue found
- PR created
- token usage recorded

### Tools Are Routed Consistently

Avoid ad hoc tool mapping inside `cli/main.py`. Add a dedicated router module, for example:

```text
tools/router.py
```

The router should:

- map `ToolType` to tool instances
- validate required args
- record tool start/end events if given a session context
- expose named tools for orchestrator workflows
- include `SearchTool`
- support fallback behavior only when explicit and tested

### Planning Uses Context

Planner should receive:

- user task
- repo path
- selected playbook content
- relevant knowledge notes
- optional codebase search snippets
- repo metadata

The CLI already accepts `--playbook`; this must be connected.

### Execution Is Iterative

Executor should loop until one of these outcomes:

- step completed
- step failed and should trigger replan
- step skipped
- session needs human input
- max iterations reached

Do not rely on a single LLM response and single tool call per step.

### Replanning Continues When Possible

Replanner decisions should change execution:

- `investigate`: insert diagnostic steps
- `fix`: replace or insert revised steps
- `skip_and_log`: mark failed step skipped and continue if safe
- `escalate`: persist status and require human input

### GitHub Workflow Is End-To-End

The target GitHub flow:

```text
create branch -> edit files -> run tests -> commit -> push -> create PR -> review -> fix -> update PR
```

Current implementation stops short of this. It must be corrected.

### Quality Gates Are First-Class

Every large agent improvement must have:

- unit tests
- integration-style tests with mocks/temp repos where feasible
- `ruff check .`
- `pytest tests/ -q --basetemp .pytest_tmp`
- updated docs for behavior changes

