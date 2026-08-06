class ProcessOperationPolicy:
    """Safety rules for operations that can stop Windows processes."""

    PROTECTED_PROCESS_NAMES = frozenset({
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
    })
    PROTECTED_PROCESS_IDS = frozenset({0, 4})

    @classmethod
    def is_protected(cls, pid: int, process_name: str, arc3_pid: int) -> bool:
        normalized_name = (process_name or "").strip().casefold()
        return (
            pid == arc3_pid
            or pid in cls.PROTECTED_PROCESS_IDS
            or normalized_name in cls.PROTECTED_PROCESS_NAMES
        )
