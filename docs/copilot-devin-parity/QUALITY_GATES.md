# Quality Gates

These gates should be used throughout the long-running Copilot session.

## Required Commands

Run from repository root.

```powershell
pytest tests/ -q --basetemp .pytest_tmp
ruff check .
```

Use `--basetemp .pytest_tmp` because the default Windows temp directory may fail
with permission errors in this environment.

If mypy is installed:

```powershell
mypy .
```

If mypy is not installed, either add it to an appropriate dependency group or record
that it was unavailable in `PROGRESS.md`.

## Suggested Focused Test Commands

```powershell
pytest tests/test_executor.py -q --basetemp .pytest_tmp
pytest tests/test_replanner.py -q --basetemp .pytest_tmp
pytest tests/test_planner.py -q --basetemp .pytest_tmp
pytest tests/test_pr_reviewer.py -q --basetemp .pytest_tmp
pytest tests/test_knowledge_base.py -q --basetemp .pytest_tmp
pytest tests/test_codebase_index.py -q --basetemp .pytest_tmp
```

Add new focused tests as new behavior is implemented.

## Behavioral Acceptance Checklist

### Runtime

- CLI calls a service layer rather than assembling all dependencies inline.
- Session status transitions are persisted.
- Events are persisted for planning, tool calls, replanning, review, and completion.
- Token usage is recorded or explicitly documented as not available from the backend.

### Planner Context

- Playbook content reaches planner context.
- Relevant knowledge reaches planner context.
- Context usage is recorded in session events.
- Missing playbooks produce clear errors.

### Tooling

- Shell, editor, git, browser, and search route through the same router.
- Unknown tools produce clear errors.
- Tool failures preserve error details.
- Search works when an index exists and fails gracefully when it does not.

### Executor

- A step can perform more than one tool call.
- Tool results are fed into subsequent model calls.
- Step completion is explicit.
- Max iteration failure is clear and tested.

### Replanner

- FIX can insert/replace steps.
- SKIP_AND_LOG can continue only when dependencies remain valid.
- ESCALATE persists session state.
- Replan loop has a hard limit.

### GitHub

- Branch creation is tested.
- Commit handles no-op clean working tree.
- Push occurs before PR creation.
- PR creation handles missing token and missing remote cleanly.
- Remote slug parsing handles HTTPS and SSH GitHub remotes.

### Scheduler

- There is a long-running scheduler mode.
- Scheduled tasks call the same service/runtime as CLI.
- Failures are logged and do not crash the scheduler loop unexpectedly.

## Documentation Gate

After any behavior change:

- Update root `README.md` if user-facing commands changed.
- Update this folder if the plan changed.
- Update `PROGRESS.md` with:
  - completed items
  - files changed
  - commands run
  - test results
  - blockers

## Cleanup Gate

Before final response:

- Remove generated cache/temp directories unless intentionally ignored:
  - `.pytest_tmp`
  - `.pytest_cache`
  - `.ruff_cache`
- Do not remove user files.
- Do not run destructive git cleanup.

