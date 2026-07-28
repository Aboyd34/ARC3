import json
from datetime import datetime

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.windows_info import WindowsInfoService
from app.workers.callable_worker import CallableWorker


class InformationCard(QFrame):
    def __init__(self, title_text):
        super().__init__()

        self.setObjectName("wideCard")

        self.title = QLabel(title_text)
        self.title.setObjectName("cardTitle")

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(9)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        layout.addWidget(self.title)
        layout.addLayout(self.content_layout)

    def clear_rows(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

            if item.layout():
                self.clear_layout(item.layout())

    def add_row(self, label_text, value_text):
        row = QHBoxLayout()
        row.setSpacing(18)

        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        label.setMinimumWidth(165)

        value = QLabel(str(value_text))
        value.setObjectName("systemValue")
        value.setWordWrap(True)
        value.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )

        row.addWidget(label)
        row.addWidget(value, 1)

        self.content_layout.addLayout(row)

    def add_section_text(self, text):
        label = QLabel(text)
        label.setObjectName("systemValue")
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )

        self.content_layout.addWidget(label)

    @staticmethod
    def clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

            if item.layout():
                InformationCard.clear_layout(
                    item.layout()
                )


class WindowsPage(QWidget):
    def __init__(self):
        super().__init__()

        self.service = WindowsInfoService()
        self.report_data = {}
        self.refresh_thread = None
        self.refresh_worker = None

        self.build_ui()
        QTimer.singleShot(0, self.refresh_information)

    def build_ui(self):
        title = QLabel("Windows Toolkit")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Detailed Windows, hardware, storage, network, "
            "and battery information."
        )
        subtitle.setObjectName("pageSubtitle")

        self.updated_label = QLabel("Not refreshed")
        self.updated_label.setObjectName("updatedLabel")

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(
            self.refresh_information
        )

        self.export_button = QPushButton("Export JSON Report")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.clicked.connect(
            self.export_report
        )

        actions = QHBoxLayout()
        actions.addWidget(self.updated_label)
        actions.addWidget(self.export_button)
        actions.addWidget(self.refresh_button)

        heading = QHBoxLayout()

        heading_text = QVBoxLayout()
        heading_text.setSpacing(2)
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)

        heading.addLayout(heading_text)
        heading.addStretch()
        heading.addLayout(actions)

        self.loading_bar = QProgressBar()
        self.loading_bar.setObjectName("usageBar")
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setVisible(False)

        self.system_card = InformationCard(
            "Windows and System"
        )
        self.hardware_card = InformationCard(
            "Computer Hardware"
        )
        self.bios_card = InformationCard(
            "BIOS and Motherboard"
        )
        self.memory_card = InformationCard(
            "Memory"
        )
        self.graphics_card = InformationCard(
            "Graphics"
        )
        self.storage_card = InformationCard(
            "Storage Drives"
        )
        self.network_card = InformationCard(
            "Network Adapters"
        )
        self.battery_card = InformationCard(
            "Battery"
        )

        cards_layout = QGridLayout()
        cards_layout.setHorizontalSpacing(18)
        cards_layout.setVerticalSpacing(18)

        cards_layout.addWidget(self.system_card, 0, 0)
        cards_layout.addWidget(self.hardware_card, 0, 1)
        cards_layout.addWidget(self.bios_card, 1, 0)
        cards_layout.addWidget(self.memory_card, 1, 1)
        cards_layout.addWidget(
            self.graphics_card,
            2,
            0,
            1,
            2,
        )
        cards_layout.addWidget(
            self.storage_card,
            3,
            0,
            1,
            2,
        )
        cards_layout.addWidget(
            self.network_card,
            4,
            0,
            1,
            2,
        )
        cards_layout.addWidget(
            self.battery_card,
            5,
            0,
            1,
            2,
        )

        cards_widget = QWidget()
        cards_widget.setLayout(cards_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setWidget(cards_widget)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(28, 24, 28, 28)
        page_layout.setSpacing(18)

        page_layout.addLayout(heading)
        page_layout.addWidget(self.loading_bar)
        page_layout.addWidget(scroll_area, 1)

    def refresh_information(self):
        if self.refresh_thread is not None:
            return

        self.refresh_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.loading_bar.setVisible(True)
        self.updated_label.setText(
            "Collecting system information..."
        )

        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(
            self.service.collect_all
        )
        self.refresh_worker.moveToThread(
            self.refresh_thread
        )

        self.refresh_thread.started.connect(
            self.refresh_worker.run
        )
        self.refresh_worker.succeeded.connect(
            self._information_loaded
        )
        self.refresh_worker.failed.connect(
            self._information_failed
        )
        self.refresh_worker.finished.connect(
            self.refresh_thread.quit
        )
        self.refresh_worker.finished.connect(
            self.refresh_worker.deleteLater
        )
        self.refresh_thread.finished.connect(
            self._information_finished
        )
        self.refresh_thread.finished.connect(
            self.refresh_thread.deleteLater
        )
        self.refresh_thread.start()

    def _information_loaded(self, report_data):
        self.report_data = report_data
        self.populate_cards()
        self.updated_label.setText(
            datetime.now().strftime(
                "Updated %I:%M:%S %p"
            )
        )

    def _information_failed(self, error_message):
        QMessageBox.critical(
            self,
            "Windows Information Error",
            (
                "ARC3 could not collect all system "
                f"information.\n\n{error_message}"
            ),
        )
        self.updated_label.setText(
            "Information collection failed"
        )

    def _information_finished(self):
        self.loading_bar.setVisible(False)
        self.refresh_button.setEnabled(True)
        self.export_button.setEnabled(
            bool(self.report_data)
        )
        self.refresh_worker = None
        self.refresh_thread = None

    def populate_cards(self):
        system = self.report_data.get("system", {})
        hardware = self.report_data.get("hardware", {})
        bios = self.report_data.get("bios", {})
        memory = self.report_data.get("memory", {})
        graphics = self.report_data.get("graphics", [])
        storage = self.report_data.get("storage", [])
        network = self.report_data.get("network", [])
        battery = self.report_data.get("battery", {})

        self.system_card.clear_rows()
        self.system_card.add_row(
            "Computer Name",
            system.get("computer_name", "Unknown"),
        )
        self.system_card.add_row(
            "Operating System",
            (
                f"{system.get('operating_system', 'Unknown')} "
                f"{system.get('windows_release', '')}"
            ).strip(),
        )
        self.system_card.add_row(
            "Windows Version",
            system.get("windows_version", "Unknown"),
        )
        self.system_card.add_row(
            "Architecture",
            system.get("architecture", "Unknown"),
        )
        self.system_card.add_row(
            "System Uptime",
            system.get("uptime", "Unknown"),
        )
        self.system_card.add_row(
            "Last Boot",
            system.get("boot_time", "Unknown"),
        )

        self.hardware_card.clear_rows()
        self.hardware_card.add_row(
            "Manufacturer",
            hardware.get("manufacturer", "Unknown"),
        )
        self.hardware_card.add_row(
            "Model",
            hardware.get("model", "Unknown"),
        )
        self.hardware_card.add_row(
            "Processor",
            system.get("processor", "Unknown"),
        )
        self.hardware_card.add_row(
            "Physical CPU Cores",
            hardware.get("cpu_physical_cores", 0),
        )
        self.hardware_card.add_row(
            "Logical CPU Cores",
            hardware.get("cpu_logical_cores", 0),
        )

        self.bios_card.clear_rows()
        self.bios_card.add_row(
            "Motherboard",
            (
                f"{hardware.get('motherboard_manufacturer', '')} "
                f"{hardware.get('motherboard_product', '')}"
            ).strip() or "Unknown",
        )
        self.bios_card.add_row(
            "BIOS Manufacturer",
            bios.get("manufacturer", "Unknown"),
        )
        self.bios_card.add_row(
            "BIOS Version",
            bios.get("version", "Unknown"),
        )
        self.bios_card.add_row(
            "BIOS Release Date",
            bios.get("release_date", "Unknown"),
        )
        self.bios_card.add_row(
            "Device Serial Number",
            bios.get("serial_number", "Unknown"),
        )

        self.memory_card.clear_rows()
        self.memory_card.add_row(
            "Installed RAM",
            memory.get("total", "Unknown"),
        )
        self.memory_card.add_row(
            "Available RAM",
            memory.get("available", "Unknown"),
        )
        self.memory_card.add_row(
            "Used RAM",
            memory.get("used", "Unknown"),
        )
        self.memory_card.add_row(
            "Memory Usage",
            memory.get("percentage", "Unknown"),
        )

        modules = memory.get("modules", [])

        for index, module in enumerate(modules, start=1):
            module_text = (
                f"Slot: {module.get('slot', 'Unknown')} | "
                f"Capacity: {module.get('capacity', 'Unknown')} | "
                f"Speed: {module.get('speed_mhz', 'Unknown')} MHz | "
                f"Manufacturer: "
                f"{module.get('manufacturer', 'Unknown')}"
            )
            self.memory_card.add_row(
                f"RAM Module {index}",
                module_text,
            )

        self.graphics_card.clear_rows()

        if graphics:
            for index, adapter in enumerate(
                graphics,
                start=1,
            ):
                self.graphics_card.add_row(
                    f"Graphics Adapter {index}",
                    (
                        f"{adapter.get('name', 'Unknown')} | "
                        f"Memory: "
                        f"{adapter.get('memory', 'Unknown')} | "
                        f"Driver: "
                        f"{adapter.get('driver_version', 'Unknown')} | "
                        f"Mode: "
                        f"{adapter.get('display_mode', 'Unknown')}"
                    ),
                )
        else:
            self.graphics_card.add_row(
                "Graphics",
                "No graphics information available",
            )

        self.storage_card.clear_rows()

        if storage:
            for drive in storage:
                self.storage_card.add_row(
                    drive.get("device", "Drive"),
                    (
                        f"{drive.get('file_system', 'Unknown')} | "
                        f"Used: {drive.get('used', 'Unknown')} | "
                        f"Free: {drive.get('free', 'Unknown')} | "
                        f"Total: {drive.get('total', 'Unknown')} | "
                        f"Usage: "
                        f"{drive.get('percentage', 'Unknown')}"
                    ),
                )
        else:
            self.storage_card.add_row(
                "Storage",
                "No accessible storage drives found",
            )

        self.network_card.clear_rows()

        if network:
            for adapter in network:
                ipv4 = ", ".join(
                    adapter.get("ipv4", [])
                ) or "None"

                mac = ", ".join(
                    adapter.get("mac", [])
                ) or "Unknown"

                self.network_card.add_row(
                    adapter.get("name", "Adapter"),
                    (
                        f"Status: "
                        f"{adapter.get('status', 'Unknown')} | "
                        f"Speed: "
                        f"{adapter.get('speed_mbps', 'Unknown')} Mbps | "
                        f"IPv4: {ipv4} | MAC: {mac}"
                    ),
                )
        else:
            self.network_card.add_row(
                "Network",
                "No network adapters found",
            )

        self.battery_card.clear_rows()

        if battery.get("available"):
            self.battery_card.add_row(
                "Charge",
                battery.get("percentage", "Unknown"),
            )
            self.battery_card.add_row(
                "Power Status",
                battery.get("power_status", "Unknown"),
            )
            self.battery_card.add_row(
                "Estimated Time",
                battery.get(
                    "remaining_time",
                    "Unknown",
                ),
            )
        else:
            self.battery_card.add_row(
                "Battery",
                battery.get(
                    "status",
                    "No battery information available",
                ),
            )

    def export_report(self):
        if not self.report_data:
            QMessageBox.warning(
                self,
                "No Report",
                "Refresh the page before exporting.",
            )
            return

        default_name = (
            "ARC3_Windows_Report_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export ARC3 Windows Report",
            default_name,
            "JSON Files (*.json)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        try:
            with open(
                file_path,
                "w",
                encoding="utf-8",
            ) as report_file:
                json.dump(
                    self.report_data,
                    report_file,
                    indent=4,
                )

            QMessageBox.information(
                self,
                "Report Exported",
                f"Windows report saved to:\n\n{file_path}",
            )
        except OSError as error:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"ARC3 could not save the report.\n\n{error}",
            )
