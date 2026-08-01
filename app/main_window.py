from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.pages.dashboard_page import DashboardPage
from app.pages.android_workspace import AndroidWorkspace
from app.pages.settings_page import SettingsPage
from app.pages.windows.windows_workspace import WindowsWorkspace
from app.settings import AppSettings
from app.widgets.placeholder_page import PlaceholderPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.app_settings = AppSettings()

        self.setWindowTitle("ARC3 Toolkit")
        self.resize(1440, 880)
        self.setMinimumSize(1050, 680)

        self.navigation_names = [
            "Dashboard",
            "Windows",
            "Android",
            "Firmware",
            "Files",
            "Developer",
            "Settings",
        ]

        self.build_interface()
        self.restore_window_geometry()

    def build_interface(self):
        root = QWidget()
        root.setObjectName("applicationRoot")

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self.create_header())

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        body_layout.addWidget(self.create_sidebar())

        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")

        self.pages.addWidget(DashboardPage())
        self.pages.addWidget(WindowsWorkspace())

        self.pages.addWidget(AndroidWorkspace())

        self.pages.addWidget(
            PlaceholderPage(
                "Firmware Manager",
                (
                    "Organize firmware packages, "
                    "checksums, and job history."
                ),
            )
        )

        self.pages.addWidget(
            PlaceholderPage(
                "File Tools",
                (
                    "Search, hashing, duplicate detection, "
                    "and bulk operations."
                ),
            )
        )

        self.pages.addWidget(
            PlaceholderPage(
                "Developer Tools",
                (
                    "PowerShell, Python, Git, and "
                    "environment utilities."
                ),
            )
        )

        self.pages.addWidget(SettingsPage(self))

        body_layout.addWidget(self.pages, 1)

        body_container = QWidget()
        body_container.setLayout(body_layout)

        root_layout.addWidget(body_container, 1)

        self.setCentralWidget(root)

        status_bar = QStatusBar()
        status_bar.setObjectName("mainStatusBar")
        status_bar.showMessage("ARC3 ready")

        version_label = QLabel("Version 0.3.2")
        version_label.setObjectName("versionLabel")

        status_bar.addPermanentWidget(version_label)

        self.setStatusBar(status_bar)
        self.sidebar.setCurrentRow(0)

    def create_header(self):
        header = QFrame()
        header.setObjectName("topHeader")
        header.setFixedHeight(74)

        brand_mark = QLabel("A3")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setFixedSize(42, 42)

        brand_name = QLabel("ARC3")
        brand_name.setObjectName("brandName")

        brand_description = QLabel(
            "Advanced Repair & Computer Toolkit"
        )
        brand_description.setObjectName(
            "brandDescription"
        )

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(brand_name)
        brand_text.addWidget(brand_description)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(
            22,
            0,
            22,
            0,
        )
        header_layout.setSpacing(12)

        header_layout.addWidget(brand_mark)
        header_layout.addLayout(brand_text)
        header_layout.addStretch()

        connection_status = QLabel("System Online")
        connection_status.setObjectName(
            "connectionStatus"
        )

        header_layout.addWidget(connection_status)

        return header

    def create_sidebar(self):
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("sidebarFrame")
        sidebar_frame.setFixedWidth(242)

        navigation_label = QLabel("NAVIGATION")
        navigation_label.setObjectName(
            "navigationLabel"
        )

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setIconSize(QSize(20, 20))
        self.sidebar.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        navigation_items = [
            ("Dashboard", QStyle.SP_ComputerIcon),
            ("Windows", QStyle.SP_DesktopIcon),
            ("Android", QStyle.SP_DriveNetIcon),
            ("Firmware", QStyle.SP_DriveHDIcon),
            ("Files", QStyle.SP_DirIcon),
            (
                "Developer",
                QStyle.SP_FileDialogDetailedView,
            ),
            (
                "Settings",
                QStyle.SP_FileDialogContentsView,
            ),
        ]

        style = QApplication.style()

        for title, standard_icon in navigation_items:
            item = QListWidgetItem(
                style.standardIcon(standard_icon),
                title,
            )
            self.sidebar.addItem(item)

        self.sidebar.currentRowChanged.connect(
            self.change_page
        )

        footer = QLabel("ARC3 local toolkit")
        footer.setObjectName("sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(sidebar_frame)
        layout.setContentsMargins(12, 20, 12, 16)
        layout.setSpacing(12)

        layout.addWidget(navigation_label)
        layout.addWidget(self.sidebar, 1)
        layout.addWidget(footer)

        return sidebar_frame

    def change_page(self, index):
        if index < 0:
            return

        self.pages.setCurrentIndex(index)

        page_name = self.navigation_names[index]

        self.statusBar().showMessage(
            f"Opened {page_name}"
        )

    def restore_window_geometry(self):
        saved_geometry = (
            self.app_settings.get_geometry()
        )

        if saved_geometry:
            self.restoreGeometry(saved_geometry)

    def closeEvent(self, event):
        self.app_settings.set_geometry(
            self.saveGeometry()
        )
        self.app_settings.sync()

        event.accept()

