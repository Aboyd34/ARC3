from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when the supervisor configuration is invalid."""


@dataclass(frozen=True)
class AgentConfiguration:
    project_name: str
    protected_branches: tuple[str, ...]
    allowed_validation_commands: tuple[tuple[str, ...], ...]
    command_timeout_seconds: int
    maximum_changed_files: int
    forbidden_file_patterns: tuple[str, ...]
    ignored_paths: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> "AgentConfiguration":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ConfigurationError(
                f"Configuration file not found: {path}"
            ) from error
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(
                f"Unable to read valid JSON configuration: {error}"
            ) from error

        if not isinstance(raw, dict):
            raise ConfigurationError(
                "Configuration root must be a JSON object."
            )

        required = {
            "project_name",
            "protected_branches",
            "allowed_validation_commands",
            "command_timeout_seconds",
            "maximum_changed_files",
            "forbidden_file_patterns",
            "ignored_paths",
        }
        missing = sorted(required - set(raw))
        if missing:
            raise ConfigurationError(
                "Missing configuration fields: " + ", ".join(missing)
            )

        project_name = cls._string(raw["project_name"], "project_name")
        protected = cls._string_list(
            raw["protected_branches"],
            "protected_branches",
        )
        commands = cls._commands(raw["allowed_validation_commands"])
        timeout = cls._positive_int(
            raw["command_timeout_seconds"],
            "command_timeout_seconds",
        )
        maximum = cls._positive_int(
            raw["maximum_changed_files"],
            "maximum_changed_files",
        )
        patterns = cls._string_list(
            raw["forbidden_file_patterns"],
            "forbidden_file_patterns",
        )
        ignored = cls._string_list(raw["ignored_paths"], "ignored_paths")

        return cls(
            project_name=project_name,
            protected_branches=protected,
            allowed_validation_commands=commands,
            command_timeout_seconds=timeout,
            maximum_changed_files=maximum,
            forbidden_file_patterns=patterns,
            ignored_paths=ignored,
        )

    @staticmethod
    def _string(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(
                f"{field_name} must be a non-empty string."
            )
        return value.strip()

    @classmethod
    def _string_list(
        cls,
        value: Any,
        field_name: str,
    ) -> tuple[str, ...]:
        if not isinstance(value, list) or not value:
            raise ConfigurationError(
                f"{field_name} must be a non-empty list."
            )
        return tuple(cls._string(item, field_name) for item in value)

    @classmethod
    def _commands(cls, value: Any) -> tuple[tuple[str, ...], ...]:
        if not isinstance(value, list) or not value:
            raise ConfigurationError(
                "allowed_validation_commands must be a non-empty list."
            )

        commands = []
        for command in value:
            if not isinstance(command, list) or not command:
                raise ConfigurationError(
                    "Each validation command must be a non-empty list."
                )
            commands.append(
                tuple(
                    cls._string(part, "validation command")
                    for part in command
                )
            )
        return tuple(commands)

    @staticmethod
    def _positive_int(value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigurationError(
                f"{field_name} must be a positive integer."
            )
        return value
