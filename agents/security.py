from __future__ import annotations

import ast
import re
from pathlib import Path

from agents.configuration import AgentConfiguration
from agents.git_guard import GitGuard
from agents.models import AgentFinding, SecurityResult


class SecurityAgent:
    """Scan changed local text without exposing suspected secret values."""

    MAX_FILE_BYTES = 1_000_000
    TEXT_SUFFIXES = {
        ".py", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
        ".md", ".txt", ".ps1", ".bat", ".cmd",
    }
    SECRET_NAME = re.compile(
        r"(?i)^(password|passwd|api_?key|secret|token)$"
    )

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

    def run(self) -> SecurityResult:
        status = self.git.inspect()
        changed = tuple(
            dict.fromkeys(
                (*status.tracked_changes, *status.untracked_files)
            )
        )
        findings: list[AgentFinding] = []
        inspected: list[str] = []
        skipped: list[str] = []

        for relative in changed:
            if self._forbidden_name(relative):
                findings.append(
                    AgentFinding(
                        "HIGH",
                        "protected-filename",
                        "Filename matches a protected pattern; contents not read.",
                        relative,
                    )
                )
                skipped.append(relative)
                continue
            source = self._read_text(relative)
            if source is None:
                skipped.append(relative)
                continue
            inspected.append(relative)
            if relative.casefold().endswith(".py"):
                findings.extend(self._python_findings(relative, source))

        return SecurityResult(
            changed_files=changed,
            findings=tuple(findings),
            files_inspected=tuple(inspected),
            skipped_files=tuple(skipped),
        )

    def _python_findings(
        self,
        relative: str,
        source: str,
    ) -> list[AgentFinding]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        findings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name in {"eval", "exec"}:
                    findings.append(
                        AgentFinding(
                            "HIGH",
                            "dynamic-execution",
                            "Dynamic code execution is security-sensitive.",
                            relative,
                            node.lineno,
                        )
                    )
                if name in {"pickle.load", "pickle.loads"}:
                    findings.append(
                        AgentFinding(
                            "HIGH",
                            "unsafe-deserialization",
                            "Pickle may execute attacker-controlled code.",
                            relative,
                            node.lineno,
                        )
                    )
                if name == "yaml.load":
                    findings.append(
                        AgentFinding(
                            "WARNING",
                            "unsafe-deserialization",
                            "Confirm YAML loading uses SafeLoader.",
                            relative,
                            node.lineno,
                        )
                    )
                if name == "tempfile.mktemp":
                    findings.append(
                        AgentFinding(
                            "WARNING",
                            "insecure-temporary-file",
                            "mktemp is vulnerable to race conditions.",
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
                                "HIGH",
                                "command-injection",
                                "shell=True enables command interpretation.",
                                relative,
                                node.lineno,
                            )
                        )
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                )
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value
                    and any(
                        isinstance(target, ast.Name)
                        and self.SECRET_NAME.match(target.id)
                        for target in targets
                    )
                ):
                    findings.append(
                        AgentFinding(
                            "HIGH",
                            "suspected-secret",
                            (
                                "Possible hard-coded credential; "
                                "value intentionally redacted."
                            ),
                            relative,
                            node.lineno,
                        )
                    )
        return findings

    @staticmethod
    def _call_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = SecurityAgent._call_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    def _forbidden_name(self, relative: str) -> bool:
        from fnmatch import fnmatch

        normalized = relative.replace("\\", "/").casefold()
        basename = Path(normalized).name
        return any(
            fnmatch(normalized, pattern.casefold())
            or fnmatch(basename, pattern.casefold())
            for pattern in self.configuration.forbidden_file_patterns
        )

    def _read_text(self, relative: str) -> str | None:
        path = self.project_path / relative
        try:
            if (
                path.suffix.casefold() not in self.TEXT_SUFFIXES
                or path.is_symlink()
                or not path.is_file()
            ):
                return None
            resolved = path.resolve()
            resolved.relative_to(self.project_path)
            if resolved.stat().st_size > self.MAX_FILE_BYTES:
                return None
            return resolved.read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, ValueError):
            return None
