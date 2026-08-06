from typing import NamedTuple


class OperationResult(NamedTuple):
    """Tuple-compatible result for a user-requested operation."""

    success: bool
    message: str
