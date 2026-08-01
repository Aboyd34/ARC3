from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodexExecutionResult:
    success: bool
    final_response: str
    error: str = ""


class CodexExecutionAgent:
    """Run an approved Codex task inside the ARC3 workspace sandbox."""

    def __init__(self, project_path: Path, timeout_seconds: int = 1800) -> None:
        self.project_path = project_path.resolve()
        self.timeout_seconds = timeout_seconds
        self.executable = shutil.which("codex")

    def run(self, prompt: str, user_approved: bool) -> CodexExecutionResult:
        if not user_approved:
            return CodexExecutionResult(False, "", "Explicit user approval is required.")
        if not prompt.strip():
            return CodexExecutionResult(False, "", "Codex prompt must not be empty.")
        if not self.executable:
            return CodexExecutionResult(False, "", "Codex CLI was not found in PATH.")

        output_dir = self.project_path / "agent_output" / "codex_runs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "latest_response.md"
        environment = os.environ.copy()
        environment.update(self._load_local_openai_environment())
        arguments = [
            self.executable,
            "exec",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(self.project_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        try:
            completed = subprocess.run(
                arguments,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return CodexExecutionResult(False, "", f"Codex execution failed: {error}")

        final_response = ""
        if output_path.exists() and not output_path.is_symlink():
            final_response = output_path.read_text(encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            message = completed.stderr.strip() or "Codex returned a non-zero exit code."
            return CodexExecutionResult(False, final_response, message)
        return CodexExecutionResult(True, final_response)

    def _load_local_openai_environment(self) -> dict[str, str]:
        path = self.project_path / ".env.local"
        if not path.exists() or path.is_symlink():
            return {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                name, separator, value = line.partition("=")
                if separator and name.strip() == "OPENAI_API_KEY" and value.strip():
                    return {"OPENAI_API_KEY": value.strip().strip('"').strip("'")}
        except OSError:
            return {}
        return {}
