from __future__ import annotations

import ast
import re
from pathlib import Path

from agents.configuration import AgentConfiguration
from agents.git_guard import GitGuard
from agents.models import AgentFinding, CodeReviewResult


class CodeReviewAgent:
    """Review local Python changes with deterministic source heuristics."""

    MAX_FILE_BYTES = 1_000_000
    UNFINISHED = re.compile(r"\bTODO\b|\bFIXME\b", re.IGNORECASE)

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

    def run(self) -> CodeReviewResult:
        status = self.git.inspect()
        changed = tuple(
            dict.fromkeys(
                (*status.tracked_changes, *status.untracked_files)
            )
        )
        findings: list[AgentFinding] = []
        inspected: list[str] = []
        skipped: list[str] = []

        if status.unsafe:
            findings.append(
                AgentFinding(
                    "BLOCKER",
                    "repository-safety",
                    status.error or "Repository state is unsafe.",
                )
            )

        for relative in changed:
            source = self._read_changed_file(relative)
            if source is None:
                skipped.append(relative)
                continue
            inspected.append(relative)
            if not relative.casefold().endswith(".py"):
                continue
            findings.extend(self._python_findings(relative, source))
            for line_number, line in enumerate(source.splitlines(), 1):
                if self.UNFINISHED.search(line):
                    findings.append(
                        AgentFinding(
                            "INFO",
                            "unfinished-work",
                            "Changed code contains an unfinished-work marker.",
                            relative,
                            line_number,
                        )
                    )

        app_modules = {
            Path(path).stem
            for path in changed
            if path.replace("\\", "/").startswith("app/")
            and path.endswith(".py")
        }
        test_text = "\n".join(
            path.casefold() for path in changed
            if path.replace("\\", "/").startswith("tests/")
        )
        for module in sorted(app_modules):
            if module.casefold() not in test_text:
                findings.append(
                    AgentFinding(
                        "WARNING",
                        "test-coverage",
                        "No changed test filename obviously covers this module.",
                        next(
                            path for path in changed
                            if Path(path).stem == module
                        ),
                    )
                )

        return CodeReviewResult(
            changed_files=changed,
            findings=tuple(findings),
            files_inspected=tuple(inspected),
            skipped_files=tuple(skipped),
        )

    @staticmethod
    def _python_findings(
        relative: str,
        source: str,
    ) -> list[AgentFinding]:
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            return [
                AgentFinding(
                    "ERROR",
                    "syntax-error",
                    "Changed Python file could not be parsed.",
                    relative,
                    error.lineno,
                )
            ]

        findings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"eval", "exec"}
                ):
                    findings.append(
                        AgentFinding(
                            "ERROR",
                            "dynamic-execution",
                            "Dynamic code execution requires manual review.",
                            relative,
                            node.lineno,
                        )
                    )
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        findings.append(
                            AgentFinding(
                                "BLOCKER",
                                "unsafe-subprocess",
                                "subprocess shell=True is prohibited.",
                                relative,
                                node.lineno,
                            )
                        )
            if (
                isinstance(node, ast.ExceptHandler)
                and (
                    node.type is None
                    or (
                        isinstance(node.type, ast.Name)
                        and node.type.id in {"Exception", "BaseException"}
                    )
                )
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            ):
                findings.append(
                    AgentFinding(
                        "WARNING",
                        "swallowed-exception",
                        "A broad exception is silently ignored.",
                        relative,
                        node.lineno,
                    )
                )
        return findings

    def _read_changed_file(self, relative: str) -> str | None:
        path = self.project_path / relative
        try:
            if path.is_symlink() or not path.is_file():
                return None
            resolved = path.resolve()
            resolved.relative_to(self.project_path)
            if resolved.stat().st_size > self.MAX_FILE_BYTES:
                return None
            return resolved.read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, ValueError):
            return None
