from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.device_models import DeviceState, OperationResult, ProfessionalOperationRequest


class AndroidAuditLogger:
    SENSITIVE_KEY = re.compile(r"token|password|secret|credential", re.IGNORECASE)

    def __init__(self, log_root: Path | None = None) -> None:
        self.log_root = log_root or Path.cwd() / "logs" / "android"

    def record(self, request: ProfessionalOperationRequest, device: DeviceState, result: OperationResult) -> Path:
        self.log_root.mkdir(parents=True, exist_ok=True)
        safe_serial = re.sub(r"[^A-Za-z0-9_.-]", "_", device.serial)[:80] or "unknown"
        path = self.log_root / f"{datetime.now().date().isoformat()}_{safe_serial}.log"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "case_id": request.case_id,
            "technician_id": request.technician_id,
            "operation": request.operation.value,
            "device": device.to_dict(),
            "result": {"success": result.success, "message": result.message,
                       "error_code": result.error_code, "data": result.data},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.sanitize(entry), sort_keys=True) + "\n")
        return path

    @classmethod
    def sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: "[REDACTED]" if cls.SENSITIVE_KEY.search(str(key)) else cls.sanitize(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [cls.sanitize(item) for item in value]
        return value
