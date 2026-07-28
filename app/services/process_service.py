import os
from typing import Any

import psutil


class ProcessService:
    PROTECTED_PROCESS_NAMES = {
        "system",
        "registry",
        "memory compression",
        "secure system",
        "system idle process",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "smss.exe",
    }

    def __init__(self):
        self.arc3_pid = os.getpid()
        self._primed = False

    def collect_processes(self) -> list[dict[str, Any]]:
        processes = []

        attributes = [
            "pid",
            "name",
            "username",
            "status",
            "memory_info",
            "num_threads",
            "create_time",
            "exe",
        ]

        for process in psutil.process_iter(attributes):
            try:
                information = process.info

                memory_info = information.get("memory_info")
                memory_bytes = (
                    memory_info.rss if memory_info else 0
                )

                cpu_percent = process.cpu_percent(interval=None)

                processes.append(
                    {
                        "name": information.get("name") or "Unknown",
                        "pid": information.get("pid", 0),
                        "cpu": round(cpu_percent, 1),
                        "memory_mb": round(
                            memory_bytes / 1024 / 1024,
                            1,
                        ),
                        "status": information.get("status") or "Unknown",
                        "username": information.get("username") or "",
                        "threads": information.get("num_threads") or 0,
                        "exe": information.get("exe") or "",
                    }
                )

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                continue

        if not self._primed:
            self._primed = True

        return processes

    def get_process_details(self, pid: int) -> dict[str, Any]:
        process = psutil.Process(pid)

        try:
            parent = process.parent()
            parent_text = (
                f"{parent.name()} ({parent.pid})"
                if parent
                else "None"
            )
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            parent_text = "Unavailable"

        try:
            command_line = " ".join(process.cmdline())
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            command_line = "Unavailable"

        try:
            executable = process.exe()
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            executable = "Unavailable"

        try:
            username = process.username()
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            username = "Unavailable"

        try:
            memory = process.memory_info().rss / 1024 / 1024
            memory_text = f"{memory:.1f} MB"
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            memory_text = "Unavailable"

        try:
            cpu_times = process.cpu_times()
            cpu_time = cpu_times.user + cpu_times.system
            cpu_time_text = f"{cpu_time:.2f} seconds"
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            cpu_time_text = "Unavailable"

        return {
            "name": process.name(),
            "pid": process.pid,
            "status": process.status(),
            "username": username,
            "executable": executable,
            "command_line": command_line or "None",
            "threads": process.num_threads(),
            "parent": parent_text,
            "memory": memory_text,
            "cpu_time": cpu_time_text,
        }

    def is_protected(self, pid: int, process_name: str) -> bool:
        normalized_name = process_name.strip().lower()

        if pid == self.arc3_pid:
            return True

        if pid in (0, 4):
            return True

        return normalized_name in self.PROTECTED_PROCESS_NAMES

    def terminate_process(self, pid: int) -> tuple[bool, str]:
        try:
            process = psutil.Process(pid)
            process_name = process.name()

            if self.is_protected(pid, process_name):
                return (
                    False,
                    "ARC3 blocked termination of this protected process.",
                )

            process.terminate()

            try:
                process.wait(timeout=4)
            except psutil.TimeoutExpired:
                return (
                    False,
                    "The process did not close within four seconds.",
                )

            return (
                True,
                f"{process_name} was terminated successfully.",
            )

        except psutil.NoSuchProcess:
            return False, "The process is no longer running."

        except psutil.AccessDenied:
            return (
                False,
                "Access was denied. ARC3 may need administrator privileges.",
            )

        except Exception as error:
            return False, str(error)
