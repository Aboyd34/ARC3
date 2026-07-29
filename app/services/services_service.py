from __future__ import annotations

import re
import subprocess
import time
from typing import Any

import psutil


class ServicesService:
    """Discover and control Windows services."""

    SUPPORTED_ACTIONS = {
        "start": "start",
        "stop": "stop",
        "pause": "pause",
        "resume": "continue",
    }
    TARGET_STATUS = {
        "start": "running",
        "stop": "stopped",
        "pause": "paused",
        "resume": "running",
    }
    SERVICE_NAME_PATTERN = re.compile(r"^[^\\/\x00-\x1f]{1,256}$")

    def collect_services(self) -> list[dict[str, Any]]:
        """Return all services with stable display values."""

        services = []

        for service in psutil.win_service_iter():
            try:
                details = service.as_dict()
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                details = self._collect_partial_details(service)

            service_name = details.get("name")
            if not service_name:
                continue

            services.append(
                {
                    "name": str(service_name),
                    "display_name": str(
                        details.get("display_name") or service_name
                    ),
                    "status": self._display_status(
                        details.get("status")
                    ),
                    "startup_type": self._display_start_type(
                        details.get("start_type")
                    ),
                    "pid": details.get("pid") or 0,
                    "description": str(
                        details.get("description") or ""
                    ),
                }
            )

        services.sort(
            key=lambda item: (
                item["display_name"].casefold(),
                item["name"].casefold(),
            )
        )
        return services

    @staticmethod
    def _collect_partial_details(service) -> dict[str, Any]:
        details = {}
        accessors = {
            "name": service.name,
            "display_name": service.display_name,
            "status": service.status,
            "start_type": service.start_type,
            "pid": service.pid,
            "description": service.description,
        }

        for field, accessor in accessors.items():
            try:
                details[field] = accessor()
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                details[field] = None

        return details

    @staticmethod
    def _display_status(status: Any) -> str:
        normalized = str(status or "unknown").replace("_", " ")
        return normalized.title()

    @staticmethod
    def _display_start_type(start_type: Any) -> str:
        normalized = str(start_type or "unknown").replace("_", " ")
        return normalized.title()

    def perform_action(
        self,
        service_name: str,
        action: str,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        """Run one supported service action and wait for its target state."""

        valid, message = self._validate_request(service_name, action)
        if not valid:
            return self._result(False, action, message, "unsupported")

        try:
            current_status = self._service_status(service_name)
        except psutil.NoSuchProcess:
            return self._result(
                False,
                action,
                f"The service “{service_name}” no longer exists.",
                "missing",
            )
        except psutil.AccessDenied:
            return self._result(
                False,
                action,
                "Access was denied while reading the service.",
                "access_denied",
            )
        except OSError as error:
            return self._result(False, action, str(error), "windows_error")

        if action == "restart":
            return self._restart_service(
                service_name,
                current_status,
                timeout,
            )

        target_status = self.TARGET_STATUS[action]
        if current_status == target_status:
            return self._result(
                True,
                action,
                (
                    f"{service_name} is already "
                    f"{self._display_status(target_status).lower()}."
                ),
                "already_in_state",
            )

        result = self._run_control(
            service_name,
            self.SUPPORTED_ACTIONS[action],
            action,
        )
        if not result["success"]:
            return result

        return self._wait_for_status(
            service_name,
            target_status,
            action,
            timeout,
        )

    def _restart_service(
        self,
        service_name: str,
        current_status: str,
        timeout: float,
    ) -> dict[str, Any]:
        if current_status != "stopped":
            stop_result = self._run_control(
                service_name,
                "stop",
                "restart",
            )
            if not stop_result["success"]:
                return stop_result

            stopped = self._wait_for_status(
                service_name,
                "stopped",
                "restart",
                timeout,
            )
            if not stopped["success"]:
                return stopped

        start_result = self._run_control(
            service_name,
            "start",
            "restart",
        )
        if not start_result["success"]:
            return start_result

        running = self._wait_for_status(
            service_name,
            "running",
            "restart",
            timeout,
        )
        if running["success"]:
            running["message"] = (
                f"{service_name} restarted successfully."
            )
        return running

    def _run_control(
        self,
        service_name: str,
        sc_action: str,
        requested_action: str,
    ) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                ["sc.exe", sc_action, service_name],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._result(
                False,
                requested_action,
                "The Service Control Manager command timed out.",
                "timeout",
            )
        except OSError as error:
            return self._result(
                False,
                requested_action,
                str(error),
                "windows_error",
            )

        if completed.returncode == 0:
            return self._result(
                True,
                requested_action,
                "The service accepted the requested action.",
                "accepted",
            )

        output = " ".join(
            part.strip()
            for part in (completed.stdout, completed.stderr)
            if part and part.strip()
        )
        return self._map_control_error(
            completed.returncode,
            output,
            requested_action,
        )

    def _wait_for_status(
        self,
        service_name: str,
        target_status: str,
        action: str,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                status = self._service_status(service_name)
            except psutil.NoSuchProcess:
                return self._result(
                    False,
                    action,
                    f"The service “{service_name}” no longer exists.",
                    "missing",
                )
            except psutil.AccessDenied:
                return self._result(
                    False,
                    action,
                    "Access was denied while checking service status.",
                    "access_denied",
                )
            except OSError as error:
                return self._result(
                    False,
                    action,
                    str(error),
                    "windows_error",
                )

            if status == target_status:
                return self._result(
                    True,
                    action,
                    (
                        f"{service_name} is now "
                        f"{self._display_status(target_status).lower()}."
                    ),
                    "completed",
                )

            time.sleep(0.2)

        return self._result(
            False,
            action,
            (
                f"Timed out waiting for {service_name} to become "
                f"{target_status}."
            ),
            "timeout",
        )

    @staticmethod
    def _service_status(service_name: str) -> str:
        return psutil.win_service_get(service_name).status().casefold()

    def _validate_request(
        self,
        service_name: str,
        action: str,
    ) -> tuple[bool, str]:
        if action not in {*self.SUPPORTED_ACTIONS, "restart"}:
            return False, f"Unsupported service action: {action}"
        if not isinstance(service_name, str):
            return False, "The service name is invalid."
        if not self.SERVICE_NAME_PATTERN.fullmatch(service_name):
            return False, "The service name is unsafe or malformed."
        return True, ""

    def _map_control_error(
        self,
        return_code: int,
        output: str,
        action: str,
    ) -> dict[str, Any]:
        normalized = output.casefold()
        if return_code == 5 or "access is denied" in normalized:
            return self._result(
                False,
                action,
                (
                    "Access was denied. Run ARC3 as administrator "
                    "to control this service."
                ),
                "access_denied",
            )
        if return_code == 1060 or "does not exist" in normalized:
            return self._result(
                False,
                action,
                "The selected service no longer exists.",
                "missing",
            )
        if return_code in (1052, 1056, 1061, 1062):
            return self._result(
                False,
                action,
                output or "The service does not support this action.",
                "unsupported",
            )
        if return_code in (1053, 1057):
            return self._result(
                False,
                action,
                output or "The service control request timed out.",
                "timeout",
            )
        return self._result(
            False,
            action,
            output or f"Service control failed with code {return_code}.",
            "windows_error",
        )

    @staticmethod
    def _result(
        success: bool,
        action: str,
        message: str,
        error: str,
    ) -> dict[str, Any]:
        return {
            "success": success,
            "action": action,
            "message": message,
            "error": "" if success else error,
        }
