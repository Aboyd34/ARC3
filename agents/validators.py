from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Sequence

from agents.configuration import AgentConfiguration
from agents.models import CommandResult, ValidationResult


class CommandNotAllowedError(ValueError):
    """Raised when a command is not an exact allowlist entry."""


class Validator:
    """Run only configured deterministic validation commands."""

    def __init__(
        self,
        project_path: Path,
        configuration: AgentConfiguration,
    ) -> None:
        self.project_path = project_path.resolve()
        self.configuration = configuration

    def run(self, command: Sequence[str]) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized not in self.configuration.allowed_validation_commands:
            raise CommandNotAllowedError(
                "Command is not in the exact validation allowlist."
            )

        started = time.monotonic()
        creation_flags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )

        try:
            completed = subprocess.run(
                list(normalized),
                cwd=self.project_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.configuration.command_timeout_seconds,
                shell=False,
                creationflags=creation_flags,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            duration = time.monotonic() - started
            return CommandResult(
                command=normalized,
                exit_code=None,
                duration_seconds=duration,
                stdout=self._timeout_text(error.stdout),
                stderr=self._timeout_text(error.stderr),
                timed_out=True,
                error=(
                    "Command timed out after "
                    f"{self.configuration.command_timeout_seconds} seconds."
                ),
            )
        except FileNotFoundError as error:
            return CommandResult(
                command=normalized,
                exit_code=None,
                duration_seconds=time.monotonic() - started,
                error=f"Executable not found: {error.filename}",
            )
        except OSError as error:
            return CommandResult(
                command=normalized,
                exit_code=None,
                duration_seconds=time.monotonic() - started,
                error=str(error),
            )

        return CommandResult(
            command=normalized,
            exit_code=completed.returncode,
            duration_seconds=time.monotonic() - started,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run_all(self) -> ValidationResult:
        return ValidationResult(
            commands=tuple(
                self.run(command)
                for command in self.configuration.allowed_validation_commands
            )
        )

    @staticmethod
    def _timeout_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value
