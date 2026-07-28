from __future__ import annotations

import fnmatch
from datetime import datetime
from pathlib import Path

from agents.configuration import AgentConfiguration
from agents.git_guard import GitGuard
from agents.models import (
    GitStatus,
    ReviewFinding,
    ReviewResult,
    SupervisionReport,
    ValidationResult,
)
from agents.prompt_builder import PromptBuilder
from agents.report import save_report
from agents.validators import Validator


class UnsafeRepositoryError(RuntimeError):
    """Raised when an operation is blocked by repository safety rules."""


class Supervisor:
    """Coordinate deterministic ARC3 preparation and validation."""

    def __init__(
        self,
        project_path: Path,
        configuration: AgentConfiguration,
    ) -> None:
        self.project_path = project_path.resolve()
        self.configuration = configuration
        self.git = GitGuard(
            self.project_path,
            configuration.protected_branches,
            min(configuration.command_timeout_seconds, 30),
        )
        self.validator = Validator(self.project_path, configuration)
        self.prompt_builder = PromptBuilder(
            self.project_path,
            configuration,
        )

    def status(self) -> GitStatus:
        return self.git.inspect()

    def prepare(self, task_title: str) -> Path:
        status = self.status()
        self._require_safe_repository(status, "prepare")
        return self.prompt_builder.save(task_title, status.branch)

    def validate(self) -> ValidationResult:
        return self.validator.run_all()

    def review(self) -> ReviewResult:
        status = self.status()
        changed = tuple(
            dict.fromkeys(
                (*status.tracked_changes, *status.untracked_files)
            )
        )
        findings: list[ReviewFinding] = []
        diff_check = self.git.diff_check()

        if not status.is_repository:
            findings.append(
                ReviewFinding(
                    "BLOCKER",
                    "Invalid repository",
                    status.error or "Git repository not found.",
                )
            )
        if status.detached_head:
            findings.append(
                ReviewFinding(
                    "BLOCKER",
                    "Detached HEAD",
                    "Switch to a named non-protected branch.",
                )
            )
        if status.protected_branch:
            findings.append(
                ReviewFinding(
                    "BLOCKER",
                    "Protected branch",
                    f"Current branch is {status.branch}.",
                )
            )
        if status.conflicts:
            findings.append(
                ReviewFinding(
                    "BLOCKER",
                    "Unresolved merge conflicts",
                    ", ".join(status.conflicts),
                )
            )
        if not diff_check.passed:
            findings.append(
                ReviewFinding(
                    "ERROR",
                    "Git diff validation failed",
                    (
                        diff_check.stderr.strip()
                        or diff_check.stdout.strip()
                        or diff_check.error
                    ),
                )
            )
        if len(changed) > self.configuration.maximum_changed_files:
            findings.append(
                ReviewFinding(
                    "ERROR",
                    "Changed-file threshold exceeded",
                    (
                        f"{len(changed)} files exceeds configured maximum "
                        f"{self.configuration.maximum_changed_files}."
                    ),
                )
            )

        for path in changed:
            pattern = self._forbidden_pattern(path)
            if pattern:
                findings.append(
                    ReviewFinding(
                        "BLOCKER",
                        "Potential secret or protected file",
                        (
                            f"Filename matches forbidden pattern "
                            f"“{pattern}”. Contents were not inspected."
                        ),
                        path,
                    )
                )

        findings.extend(self._test_coverage_findings(changed))
        findings.extend(self._scope_findings(changed))
        findings.append(
            ReviewFinding(
                "INFO",
                "Human semantic review required",
                (
                    "Deterministic checks cannot prove behavior, design "
                    "correctness, or feature completeness."
                ),
            )
        )

        return ReviewResult(
            findings=tuple(findings),
            changed_files=changed,
            untracked_files=status.untracked_files,
            diff_stat=self.git.diff_stat(),
            diff_check=diff_check,
        )

    def supervise(
        self,
        include_json: bool = False,
    ) -> tuple[SupervisionReport, Path, Path | None]:
        status = self.status()
        generated_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        if status.unsafe:
            report = SupervisionReport(
                generated_at=generated_at,
                decision="REJECTED",
                git_status=status,
                review=None,
                validation=None,
                notes=(self._unsafe_reason(status, "supervise"),),
            )
        else:
            review = self.review()
            validation = self.validate()
            if not validation.passed or not review.passed:
                decision = "REJECTED"
            elif review.requires_manual_review:
                decision = "MANUAL REVIEW REQUIRED"
            else:
                decision = "APPROVED FOR HUMAN REVIEW"
            report = SupervisionReport(
                generated_at=generated_at,
                decision=decision,
                git_status=status,
                review=review,
                validation=validation,
                notes=(
                    "No commits, pushes, merges, or AI execution occurred.",
                ),
            )

        output_dir = self.project_path / "agent_output" / "reports"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        markdown_path = output_dir / f"{timestamp}_supervision.md"
        saved, json_path = save_report(
            markdown_path,
            report,
            include_json,
        )
        return report, saved, json_path

    def _require_safe_repository(
        self,
        status: GitStatus,
        operation: str,
    ) -> None:
        if status.unsafe:
            raise UnsafeRepositoryError(
                self._unsafe_reason(status, operation)
            )

    @staticmethod
    def _unsafe_reason(status: GitStatus, operation: str) -> str:
        if not status.is_repository:
            return f"Cannot {operation}: not a valid repository."
        if status.protected_branch:
            return (
                f"Cannot {operation} on protected branch "
                f"{status.branch}."
            )
        if status.detached_head:
            return f"Cannot {operation}: HEAD is detached."
        if status.conflicts:
            return (
                f"Cannot {operation}: unresolved merge conflicts exist."
            )
        return f"Cannot {operation}: unsafe repository state."

    def _forbidden_pattern(self, path: str) -> str:
        normalized = path.replace("\\", "/").casefold()
        basename = Path(normalized).name
        for pattern in self.configuration.forbidden_file_patterns:
            folded = pattern.casefold()
            if fnmatch.fnmatch(normalized, folded) or fnmatch.fnmatch(
                basename,
                folded,
            ):
                return pattern
        return ""

    def _test_coverage_findings(
        self,
        changed: tuple[str, ...],
    ) -> list[ReviewFinding]:
        findings = []
        test_text = self._combined_test_text()
        for path in changed:
            normalized = path.replace("\\", "/")
            if (
                normalized.startswith("app/")
                and normalized.endswith(".py")
                and Path(normalized).stem not in test_text
            ):
                findings.append(
                    ReviewFinding(
                        "WARNING",
                        "Changed application module lacks obvious test coverage",
                        (
                            "No test filename or test source references this "
                            "module name; verify coverage manually."
                        ),
                        path,
                    )
                )
        return findings

    def _combined_test_text(self) -> str:
        parts = []
        tests = self.project_path / "tests"
        if not tests.exists() or tests.is_symlink():
            return ""
        for path in tests.glob("test_*.py"):
            if path.is_symlink():
                continue
            try:
                parts.append(path.name.casefold())
                parts.append(
                    path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).casefold()
                )
            except OSError:
                continue
        return "\n".join(parts)

    @staticmethod
    def _scope_findings(
        changed: tuple[str, ...],
    ) -> list[ReviewFinding]:
        roots = {
            path.replace("\\", "/").split("/", 1)[0]
            for path in changed
            if path
        }
        if "app" in roots and ("agents" in roots or "arc3_agent.py" in roots):
            return [
                ReviewFinding(
                    "WARNING",
                    "Mixed application and supervisor changes",
                    (
                        "The working tree contains both ARC3 application "
                        "and supervisor-agent changes; confirm scope manually."
                    ),
                )
            ]
        return []
