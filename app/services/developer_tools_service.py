from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


@dataclass(frozen=True)
class DeveloperTool:
    name: str
    executable: str | None
    available: bool
    version: str


class DeveloperToolsService:
    TOOL_SPECS = (
        ("Python", "python", ("--version",)),
        ("PowerShell", "powershell", ("-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()")),
        ("Git", "git", ("--version",)),
        ("GitHub CLI", "gh", ("--version",)),
        ("ADB", "adb", ("version",)),
        ("Fastboot", "fastboot", ("--version",)),
    )
    TIMEOUT_SECONDS = 5

    def __init__(self, trusted_roots: tuple[str | Path, ...] | None = None):
        self.trusted_roots = tuple(
            Path(root).resolve() for root in (
                trusted_roots if trusted_roots is not None else self._default_trusted_roots()
            )
        )

    @staticmethod
    def _default_trusted_roots() -> tuple[Path, ...]:
        candidates = [Path(sys.executable).resolve().parent]
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "SystemRoot"):
            value = os.environ.get(variable)
            if value:
                candidates.append(Path(value))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs")
        configured_tools = os.environ.get("ARC3_ANDROID_PLATFORM_TOOLS")
        if configured_tools:
            candidates.append(Path(configured_tools))
        return tuple(candidates)

    def discover(self) -> tuple[DeveloperTool, ...]:
        return tuple(self._probe(name, command, arguments) for name, command, arguments in self.TOOL_SPECS)

    def _probe(self, name: str, command: str, arguments: tuple[str, ...]) -> DeveloperTool:
        executable = shutil.which(command)
        if executable is None:
            return DeveloperTool(name, None, False, "Not found on PATH")
        executable_path = Path(executable).resolve()
        if not any(executable_path.is_relative_to(root) for root in self.trusted_roots):
            return DeveloperTool(name, executable, False, "Rejected: executable is outside trusted installation paths")
        try:
            result = subprocess.run(
                [executable, *arguments], capture_output=True, text=True,
                timeout=self.TIMEOUT_SECONDS, check=False, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DeveloperTool(name, executable, False, f"Probe failed: {exc}")
        output = (result.stdout or result.stderr).strip().splitlines()
        version = output[0].strip() if output else f"Exited with code {result.returncode}"
        return DeveloperTool(name, executable, result.returncode == 0, version)

    @staticmethod
    def export_report(tools: tuple[DeveloperTool, ...], destination: str | Path) -> None:
        report = {"schema_version": 1, "tools": [asdict(tool) for tool in tools]}
        with Path(destination).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
