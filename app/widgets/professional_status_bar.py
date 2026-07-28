import shutil
import time

import psutil

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QStatusBar


class ProfessionalStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("professionalStatusBar")
        self.setSizeGripEnabled(True)

        self.cpu_label = QLabel("CPU: --")
        self.ram_label = QLabel("RAM: --")
        self.disk_label = QLabel("Disk: --")
        self.download_label = QLabel("Download: --")
        self.upload_label = QLabel("Upload: --")
        self.clock_label = QLabel("")

        self.cpu_label.setToolTip("Current total CPU usage")
        self.ram_label.setToolTip("Current physical memory usage")
        self.disk_label.setToolTip("System drive usage")
        self.download_label.setToolTip("Current download rate")
        self.upload_label.setToolTip("Current upload rate")

        self.addPermanentWidget(self.cpu_label)
        self.addPermanentWidget(self.separator())
        self.addPermanentWidget(self.ram_label)
        self.addPermanentWidget(self.separator())
        self.addPermanentWidget(self.disk_label)
        self.addPermanentWidget(self.separator())
        self.addPermanentWidget(self.download_label)
        self.addPermanentWidget(self.separator())
        self.addPermanentWidget(self.upload_label)
        self.addPermanentWidget(self.separator())
        self.addPermanentWidget(self.clock_label)

        network = psutil.net_io_counters()

        self.previous_received = network.bytes_recv
        self.previous_sent = network.bytes_sent
        self.previous_time = time.monotonic()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1500)

        self.update_status()

    @staticmethod
    def separator():
        label = QLabel("│")
        label.setObjectName("statusSeparator")
        return label

    @staticmethod
    def format_rate(bytes_per_second):
        value = max(0.0, float(bytes_per_second))

        if value >= 1024 ** 3:
            return f"{value / (1024 ** 3):.1f} GB/s"

        if value >= 1024 ** 2:
            return f"{value / (1024 ** 2):.1f} MB/s"

        if value >= 1024:
            return f"{value / 1024:.1f} KB/s"

        return f"{value:.0f} B/s"

    def update_status(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()

            system_drive = "C:\\"
            disk = shutil.disk_usage(system_drive)
            disk_percent = (
                disk.used / disk.total * 100
                if disk.total
                else 0
            )

            network = psutil.net_io_counters()
            current_time = time.monotonic()
            elapsed = max(
                current_time - self.previous_time,
                0.001,
            )

            download_rate = (
                network.bytes_recv - self.previous_received
            ) / elapsed

            upload_rate = (
                network.bytes_sent - self.previous_sent
            ) / elapsed

            self.previous_received = network.bytes_recv
            self.previous_sent = network.bytes_sent
            self.previous_time = current_time

            self.cpu_label.setText(f"CPU: {cpu:.0f}%")
            self.ram_label.setText(
                f"RAM: {memory.percent:.0f}%"
            )
            self.disk_label.setText(
                f"Disk: {disk_percent:.0f}%"
            )
            self.download_label.setText(
                f"↓ {self.format_rate(download_rate)}"
            )
            self.upload_label.setText(
                f"↑ {self.format_rate(upload_rate)}"
            )

            self.clock_label.setText(
                time.strftime("%I:%M:%S %p")
            )

        except Exception:
            self.cpu_label.setText("CPU: unavailable")
