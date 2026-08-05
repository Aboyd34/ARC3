from PySide6.QtWidgets import (
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.pages.windows.processes_tab import ProcessesTab
from app.pages.windows.devices_tab import DevicesTab
from app.pages.windows.startup_tab import StartupTab
from app.pages.windows_page import WindowsPage


class WindowsWorkspace(QWidget):
    def __init__(self):
        super().__init__()

        self.build_ui()

    def build_ui(self):
        title = QLabel("Windows")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "System administration, monitoring, diagnostics, "
            "maintenance, and recovery tools."
        )
        subtitle.setObjectName("pageSubtitle")

        self.tabs = QTabWidget()
        self.tabs.setObjectName("windowsTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)

        self.overview_tab = WindowsPage()
        self.processes_tab = ProcessesTab()
        self.startup_tab = StartupTab()
        self.devices_tab = DevicesTab()

        self.tabs.addTab(
            self.overview_tab,
            "Overview",
        )
        self.tabs.addTab(
            self.processes_tab,
            "Processes",
        )

        self.tabs.addTab(
            self.create_future_tab(
                "Services",
                "Windows service controls will be added here.",
            ),
            "Services",
        )

        self.tabs.addTab(
            self.startup_tab,
            "Startup",
        )

        self.tabs.addTab(
            self.devices_tab,
            "Devices",
        )

        self.tabs.addTab(
            self.create_future_tab(
                "Storage",
                "Storage analysis and cleanup tools will be added here.",
            ),
            "Storage",
        )

        self.tabs.addTab(
            self.create_future_tab(
                "Network",
                "Network diagnostics and adapter tools will be added here.",
            ),
            "Network",
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(12)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.tabs, 1)

    @staticmethod
    def create_future_tab(title_text, description_text):
        page = QWidget()

        title = QLabel(title_text)
        title.setObjectName("placeholderTitle")

        description = QLabel(description_text)
        description.setObjectName("placeholderDescription")
        description.setWordWrap(True)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(12)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch()

        return page
