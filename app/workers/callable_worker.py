from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


LOGGER = logging.getLogger(__name__)


class CallableWorker(QObject):
    """Run a no-argument callable and report its result through Qt signals."""

    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as error:
            LOGGER.exception("ARC3 background operation failed")
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()
