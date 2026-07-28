import platform
from datetime import datetime

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StatCard(QFrame):
    def __init__(self, title_text):
        super().__init__()

        self.setObjectName("statCard")

        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("cardTitle")

        self.value_label = QLabel("0%")
        self.value_label.setObjectName("cardValue")

        self.details_label = QLabel("Loading...")
        self.details_label.setObjectName("cardDetails")

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("usageBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.details_label)
        layout.addStretch()
        layout.addWidget(self.progress_bar)

    def update_value(self, percentage, details):
        self.value_label.setText(f"{percentage}%")
        self.details_label.setText(details)
        self.progress_bar.setValue(percentage)


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()

        self.cpu_card = StatCard("CPU Usage")
        self.ram_card = StatCard("Memory Usage")
        self.disk_card = StatCard("System Drive")

        self.updated_label = QLabel("Last updated: --")
        self.updated_label.setObjectName("updatedLabel")

        self.refresh_button = QPushButton("Refresh Now")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.update_stats)

        self.system_card = self.create_system_card()

        self.build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

        self.update_stats()

    def build_ui(self):
        heading = QLabel("System Dashboard")
        heading.setObjectName("pageTitle")

        subtitle = QLabel(
            "Live performance and system information for this computer."
        )
        subtitle.setObjectName("pageSubtitle")

        heading_layout = QVBoxLayout()
        heading_layout.setSpacing(2)
        heading_layout.addWidget(heading)
        heading_layout.addWidget(subtitle)

        actions_layout = QHBoxLayout()
        actions_layout.addStretch()
        actions_layout.addWidget(self.updated_label)
        actions_layout.addWidget(self.refresh_button)

        top_layout = QHBoxLayout()
        top_layout.addLayout(heading_layout)
        top_layout.addStretch()
        top_layout.addLayout(actions_layout)

        cards = QGridLayout()
        cards.setHorizontalSpacing(18)
        cards.setVerticalSpacing(18)

        cards.addWidget(self.cpu_card, 0, 0)
        cards.addWidget(self.ram_card, 0, 1)
        cards.addWidget(self.disk_card, 0, 2)
        cards.addWidget(self.system_card, 1, 0, 1, 3)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(28, 24, 28, 28)
        page_layout.setSpacing(22)

        page_layout.addLayout(top_layout)
        page_layout.addLayout(cards)
        page_layout.addStretch()

    def create_system_card(self):
        card = QFrame()
        card.setObjectName("wideCard")

        title = QLabel("System Information")
        title.setObjectName("cardTitle")

        self.os_value = QLabel()
        self.computer_value = QLabel()
        self.processor_value = QLabel()
        self.uptime_value = QLabel()

        for label in (
            self.os_value,
            self.computer_value,
            self.processor_value,
            self.uptime_value,
        ):
            label.setObjectName("systemValue")
            label.setWordWrap(True)

        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(14)

        grid.addWidget(self.create_field_label("Operating System"), 0, 0)
        grid.addWidget(self.os_value, 0, 1)

        grid.addWidget(self.create_field_label("Computer Name"), 1, 0)
        grid.addWidget(self.computer_value, 1, 1)

        grid.addWidget(self.create_field_label("Processor"), 0, 2)
        grid.addWidget(self.processor_value, 0, 3)

        grid.addWidget(self.create_field_label("System Uptime"), 1, 2)
        grid.addWidget(self.uptime_value, 1, 3)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)

        layout.addWidget(title)
        layout.addLayout(grid)

        return card

    @staticmethod
    def create_field_label(text):
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def update_stats(self):
        cpu = int(psutil.cpu_percent(interval=None))

        memory = psutil.virtual_memory()
        ram = int(memory.percent)

        disk = psutil.disk_usage("C:\\")
        disk_percent = int(disk.percent)

        self.cpu_card.update_value(
            cpu,
            f"{psutil.cpu_count(logical=True)} logical processors",
        )

        used_ram = self.format_bytes(memory.used)
        total_ram = self.format_bytes(memory.total)

        self.ram_card.update_value(
            ram,
            f"{used_ram} used of {total_ram}",
        )

        used_disk = self.format_bytes(disk.used)
        total_disk = self.format_bytes(disk.total)

        self.disk_card.update_value(
            disk_percent,
            f"{used_disk} used of {total_disk}",
        )

        self.os_value.setText(
            f"{platform.system()} {platform.release()} "
            f"({platform.version()})"
        )

        self.computer_value.setText(platform.node() or "Unknown")

        self.processor_value.setText(
            platform.processor()
            or platform.machine()
            or "Unknown"
        )

        uptime_seconds = (
            datetime.now().timestamp() - psutil.boot_time()
        )

        self.uptime_value.setText(
            self.format_uptime(int(uptime_seconds))
        )

        self.updated_label.setText(
            datetime.now().strftime("Updated %I:%M:%S %p")
        )

    @staticmethod
    def format_bytes(value):
        size = float(value)

        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024

        return f"{size:.1f} PB"

    @staticmethod
    def format_uptime(seconds):
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days:
            return f"{days}d {hours}h {minutes}m"

        return f"{hours}h {minutes}m"
