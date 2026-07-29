# ARC3 Project Instructions

## Repository safety

- Always inspect the current Git branch before making changes.
- Never modify `main` directly unless the user explicitly requests it.
- Stop immediately if the current branch does not match the requested phase branch.
- Never run `git reset --hard`, `git clean -fd`, force push, or destructive repository commands.
- Never commit, merge, tag, or push unless explicitly requested.
- Never delete backups or user-created files without explicit permission.

## Architecture

- ARC3 is a Windows desktop application built with Python and PySide6.
- Preserve the existing application architecture.
- Reuse existing services, tabs, workers, notifications, themes, dialogs, and status-bar patterns.
- Keep UI code separate from service and system-control logic.
- Use existing `CallableWorker` and `QThread` patterns for slow operations.
- Never block the UI thread.
- Avoid broad rewrites when a scoped change is sufficient.
- Do not modify unrelated files.

## Windows operations

- Use argument-list subprocess calls.
- Never use `shell=True`.
- Never interpolate untrusted text into commands.
- Handle access denied, missing resources, timeouts, unsupported operations, and Windows errors cleanly.
- Require confirmation for state-changing or destructive actions.
- Confirmation dialogs must default to No.
- Prefer reversible operations.
- Do not permanently delete system configuration unless explicitly required and approved.

## Interface consistency

- Follow existing ARC3 page and tab conventions.
- Preserve current theme behavior.
- Reuse ARC3 notifications and status-bar reporting.
- Integrate F5 through the existing refresh dispatcher.
- Ensure the active page refreshes exactly once.
- Preserve keyboard navigation, sorting, search, and selection behavior where applicable.

## Quality requirements

Before reporting completion:

- Inspect all changed files.
- Run `python -m compileall app`.
- Run all relevant tests.
- Run the full test suite when practical.
- Perform a launch smoke test when UI files change.
- Run `git diff --check`.
- Run `git status --short`.
- Confirm no unrelated files changed.
- Confirm no secrets, credentials, generated files, or local environment files were added.

## Completion report

Every completion report must include:

- Current branch
- Files changed
- Architecture used
- Commands run
- Tests and results
- Smoke-test result
- Git status
- Known limitations
- Any actions that still require manual verification
