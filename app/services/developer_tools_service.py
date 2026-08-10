from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import subprocess


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

    def discover(self) -> tuple[DeveloperTool, ...]:
        return tuple(self._probe(name, command, arguments) for name, command, arguments in self.TOOL_SPECS)

    def _probe(self, name: str, command: str, arguments: tuple[str, ...]) -> DeveloperTool:
        executable = shutil.which(command)
        if executable is None:
            return DeveloperTool(name, None, False, "Not found on PATH")
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
        Path(destination).write_text(json.dumps(report, indent=2), encoding="utf-8")
