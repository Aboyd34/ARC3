from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int | None
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command"] = list(self.command)
        data["passed"] = self.passed
        return data


@dataclass(frozen=True)
class GitStatus:
    project_path: Path
    is_repository: bool
    branch: str = ""
    detached_head: bool = False
    protected_branch: bool = False
    tracked_changes: tuple[str, ...] = ()
    untracked_files: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    remotes: dict[str, str] = field(default_factory=dict)
    latest_commit: str = ""
    error: str = ""

    @property
    def clean(self) -> bool:
        return not self.tracked_changes and not self.untracked_files

    @property
    def unsafe(self) -> bool:
        return (
            not self.is_repository
            or self.detached_head
            or self.protected_branch
            or bool(self.conflicts)
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["project_path"] = str(self.project_path)
        data["clean"] = self.clean
        data["unsafe"] = self.unsafe
        return data


@dataclass(frozen=True)
class ValidationResult:
    commands: tuple[CommandResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.commands) and all(
            command.passed for command in self.commands
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "commands": [command.to_dict() for command in self.commands],
        }


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    title: str
    details: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewResult:
    findings: tuple[ReviewFinding, ...]
    changed_files: tuple[str, ...]
    untracked_files: tuple[str, ...]
    diff_stat: str
    diff_check: CommandResult

    @property
    def passed(self) -> bool:
        return not any(
            finding.severity in {"ERROR", "BLOCKER"}
            for finding in self.findings
        ) and self.diff_check.passed

    @property
    def requires_manual_review(self) -> bool:
        return any(
            finding.severity == "WARNING"
            for finding in self.findings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "requires_manual_review": self.requires_manual_review,
            "findings": [finding.to_dict() for finding in self.findings],
            "changed_files": list(self.changed_files),
            "untracked_files": list(self.untracked_files),
            "diff_stat": self.diff_stat,
            "diff_check": self.diff_check.to_dict(),
        }


@dataclass(frozen=True)
class SupervisionReport:
    generated_at: str
    decision: str
    git_status: GitStatus
    review: ReviewResult | None
    validation: ValidationResult | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "decision": self.decision,
            "git_status": self.git_status.to_dict(),
            "review": self.review.to_dict() if self.review else None,
            "validation": (
                self.validation.to_dict() if self.validation else None
            ),
            "notes": list(self.notes),
        }
