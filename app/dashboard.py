from __future__ import annotations

from functools import partial

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from app.services.health_engine import HealthEngine, HealthSnapshot, HealthState
from app.workers.callable_worker import CallableWorker


class HealthCard(QFrame):
    def __init__(self, title: str, show_progress: bool = True) -> None:
        super().__init__()
        self.setObjectName("statCard")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.value_label = QLabel("--")
        self.value_label.setObjectName("cardValue")
        self.state_label = QLabel("Collecting health data...")
        self.state_label.setObjectName("systemValue")
        self.details_label = QLabel("Loading...")
        self.details_label.setObjectName("cardDetails")
        self.details_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("usageBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(show_progress)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.details_label)
        layout.addStretch()
        layout.addWidget(self.progress_bar)

    def update_metric(self, value: str, state: HealthState, detail: str) -> None:
        self.value_label.setText(value)
        self.state_label.setText(state.name)
        self.details_label.setText(detail)
        if self.progress_bar.isVisible():
            try:
                self.progress_bar.setValue(int(float(value.rstrip("%"))))
            except ValueError:
                self.progress_bar.setValue(0)


class DashboardPage(QWidget):
    REFRESH_INTERVAL_MS = 10_000

    def __init__(
        self,
        main_window=None,
        service: HealthEngine | None = None,
        auto_refresh: bool = True,
    ) -> None:
        super().__init__()
        self.main_window = main_window
        self.service = service or HealthEngine()
        self.snapshot: HealthSnapshot | None = None
        self.refresh_thread = None
        self.refresh_worker = None
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        if auto_refresh:
            self.timer.start(self.REFRESH_INTERVAL_MS)
            QTimer.singleShot(0, self.refresh)

    def _build_ui(self) -> None:
        heading = QLabel("System Dashboard")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("Read-only Windows and ARC3 application health overview.")
        subtitle.setObjectName("pageSubtitle")
        self.updated_label = QLabel("Not refreshed")
        self.updated_label.setObjectName("updatedLabel")
        self.refresh_button = QPushButton("Refresh Now")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh)

        heading_text = QVBoxLayout()
        heading_text.setSpacing(2)
        heading_text.addWidget(heading)
        heading_text.addWidget(subtitle)
        top = QHBoxLayout()
        top.addLayout(heading_text)
        top.addStretch()
        top.addWidget(self.updated_label)
        top.addWidget(self.refresh_button)

        self.overall_card = HealthCard("Overall Health", show_progress=False)
        self.cpu_card = HealthCard("CPU Utilization")
        self.memory_card = HealthCard("Memory Utilization")
        self.storage_card = HealthCard("Primary Storage")
        self.uptime_card = HealthCard("Windows Uptime", show_progress=False)
        self.application_card = HealthCard("ARC3 Application Health", show_progress=False)
        cards = QGridLayout()
        cards.setSpacing(18)
        for index, card in enumerate((
            self.overall_card, self.cpu_card, self.memory_card,
            self.storage_card, self.uptime_card, self.application_card,
        )):
            cards.addWidget(card, index // 3, index % 3)

        warning_card = QFrame()
        warning_card.setObjectName("wideCard")
        warning_title = QLabel("Active Warnings")
        warning_title.setObjectName("cardTitle")
        self.warnings_label = QLabel("Health data has not been collected.")
        self.warnings_label.setObjectName("systemValue")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        warning_layout = QVBoxLayout(warning_card)
        warning_layout.setContentsMargins(22, 20, 22, 20)
        warning_layout.addWidget(warning_title)
        warning_layout.addWidget(self.warnings_label)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addLayout(cards)
        content_layout.addWidget(warning_card)
        content_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)

    def refresh(self) -> bool:
        """F5/timer entry point; start no more than one snapshot collection."""
        if not isValid(self) or not isValid(self.refresh_button):
            return False
        if self.refresh_thread is not None:
            return False
        active_workers = 0
        if self.main_window is not None and isValid(self.main_window):
            active_workers = sum(
                thread.isRunning() for thread in self.main_window.findChildren(QThread)
            )
        self.refresh_button.setEnabled(False)
        self.updated_label.setText("Collecting health data...")
        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(partial(self.service.collect, active_workers))
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.succeeded.connect(self._snapshot_loaded)
        self.refresh_worker.failed.connect(self._snapshot_failed)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self._refresh_finished)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        self.refresh_thread.start()
        return True

    def _snapshot_loaded(self, snapshot: HealthSnapshot) -> None:
        self.snapshot = snapshot
        self.overall_card.update_metric(snapshot.overall_state.name, snapshot.overall_state, "Worst current component state")
        self.cpu_card.update_metric(f"{snapshot.cpu.value}%", snapshot.cpu.state, snapshot.cpu.detail)
        self.memory_card.update_metric(f"{snapshot.memory.value}%", snapshot.memory.state, snapshot.memory.detail)
        self.storage_card.update_metric(f"{snapshot.storage.value}%", snapshot.storage.state, snapshot.storage.detail)
        self.uptime_card.update_metric(snapshot.uptime.detail, snapshot.uptime.state, "Time since Windows last booted")
        self.application_card.update_metric(snapshot.application.state.name, snapshot.application.state, snapshot.application.detail)
        self.warnings_label.setText("\n".join(snapshot.warnings) if snapshot.warnings else "No active warnings.")
        self.updated_label.setText(snapshot.collected_at.astimezone().strftime("Updated %I:%M:%S %p"))
        self._show_status(f"System health: {snapshot.overall_state.name}")

    def _snapshot_failed(self, message: str) -> None:
        self.updated_label.setText("Health collection failed")
        self.warnings_label.setText(f"Health data unavailable: {message}")
        self._show_status("System health collection failed")

    def _refresh_finished(self) -> None:
        self.refresh_worker = None
        self.refresh_thread = None
        self.refresh_button.setEnabled(True)

    def _show_status(self, message: str) -> None:
        if self.main_window is not None and self.main_window.statusBar() is not None:
            self.main_window.statusBar().showMessage(message, 5000)
