from __future__ import annotations

from pathlib import Path

from agents.configuration import AgentConfiguration
from agents.git_guard import GitGuard
from agents.models import PlanResult
from agents.prompt_builder import PromptBuilder


class PlannerAgent:
    """Build a deterministic implementation plan from local metadata."""

    def __init__(
        self,
        project_path: Path,
        configuration: AgentConfiguration,
        git: GitGuard | None = None,
    ) -> None:
        self.project_path = project_path.resolve()
        self.configuration = configuration
        self.git = git or GitGuard(
            self.project_path,
            configuration.protected_branches,
        )
        self.prompt_builder = PromptBuilder(
            self.project_path,
            configuration,
        )

    def run(self, task_title: str) -> PlanResult:
        title = task_title.strip()
        if not title:
            raise ValueError("Task title must not be empty.")

        status = self.git.inspect()
        changed = tuple(
            dict.fromkeys(
                (*status.tracked_changes, *status.untracked_files)
            )
        )
        relevant = list(
            self.prompt_builder.relevant_existing_files(title)
        )
        for path in changed:
            if path not in relevant:
                relevant.append(path)

        roots = sorted(
            {
                path.replace("\\", "/").split("/", 1)[0]
                for path in relevant
                if path
            }
        )
        steps = [
            "Confirm repository safety and re-read AGENTS.md.",
            (
                "Inspect the relevant files"
                + (f" under: {', '.join(roots)}." if roots else ".")
            ),
            f"Implement the smallest scoped change for: {title}.",
            "Add or update focused tests without changing unrelated code.",
            "Run the configured validation commands and inspect the diff.",
        ]
        warnings = []
        if status.unsafe:
            warnings.append(
                status.error
                or "Repository state is unsafe; do not implement the plan."
            )
        if changed:
            warnings.append(
                "The working tree is already dirty; preserve existing changes."
            )

        return PlanResult(
            task_title=title,
            branch=status.branch,
            changed_files=changed,
            relevant_files=tuple(relevant[:40]),
            steps=tuple(steps),
            validation_commands=(
                self.configuration.allowed_validation_commands
            ),
            warnings=tuple(warnings),
        )
