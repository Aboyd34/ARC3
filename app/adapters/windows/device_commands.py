import subprocess
from collections.abc import Callable, Sequence
from typing import Any


class WindowsDeviceCommandAdapter:
    """Execute bounded Windows device commands without a shell."""

    def __init__(self, runner: Callable[..., Any] | None = None) -> None:
        self.runner = runner or subprocess.run

    def powershell(self, script: str, *arguments: str, timeout: int) -> Any:
        return self.runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script, *arguments],
            capture_output=True, text=True, timeout=timeout, check=False,
        )

    def pnputil(self, arguments: Sequence[str], *, timeout: int) -> Any:
        return self.runner(
            ["pnputil.exe", *arguments], capture_output=True, text=True,
            timeout=timeout, check=False,
        )

    def open_device_manager(self) -> Any:
        return subprocess.Popen(
            ["mmc.exe", "devmgmt.msc"], shell=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
