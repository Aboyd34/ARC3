from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.theme import load_theme


class SettingsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.main_window = main_window
        self.build_ui()

    def build_ui(self):
        title = QLabel("Settings")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Configure ARC3 appearance and window behavior."
        )
        subtitle.setObjectName("pageSubtitle")

        appearance_card = QFrame()
        appearance_card.setObjectName("settingsCard")

        appearance_title = QLabel("Appearance")
        appearance_title.setObjectName(
            "settingsSectionTitle"
        )

        appearance_description = QLabel(
            "Choose the visual theme used throughout ARC3."
        )
        appearance_description.setObjectName(
            "settingsDescription"
        )

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")

        saved_theme = (
            self.main_window.app_settings.get_theme()
        )

        saved_index = self.theme_combo.findData(
            saved_theme
        )

        if saved_index >= 0:
            self.theme_combo.setCurrentIndex(saved_index)

        apply_button = QPushButton("Apply Theme")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.apply_theme)

        appearance_actions = QHBoxLayout()
        appearance_actions.addWidget(self.theme_combo)
        appearance_actions.addWidget(apply_button)
        appearance_actions.addStretch()

        appearance_layout = QVBoxLayout(
            appearance_card
        )
        appearance_layout.setContentsMargins(
            22,
            20,
            22,
            20,
        )
        appearance_layout.setSpacing(10)

        appearance_layout.addWidget(appearance_title)
        appearance_layout.addWidget(
            appearance_description
        )
        appearance_layout.addLayout(
            appearance_actions
        )

        window_card = QFrame()
        window_card.setObjectName("settingsCard")

        window_title = QLabel("Window")
        window_title.setObjectName(
            "settingsSectionTitle"
        )

        window_description = QLabel(
            "ARC3 automatically remembers its size "
            "and screen position."
        )
        window_description.setObjectName(
            "settingsDescription"
        )

        reset_button = QPushButton(
            "Reset Window Position"
        )
        reset_button.setObjectName("dangerButton")
        reset_button.clicked.connect(
            self.reset_window_position
        )

        window_layout = QVBoxLayout(window_card)
        window_layout.setContentsMargins(
            22,
            20,
            22,
            20,
        )
        window_layout.setSpacing(10)

        window_layout.addWidget(window_title)
        window_layout.addWidget(window_description)
        window_layout.addWidget(
            reset_button,
            alignment=Qt.AlignLeft,
        )

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(
            28,
            24,
            28,
            28,
        )
        page_layout.setSpacing(18)

        page_layout.addWidget(title)
        page_layout.addWidget(subtitle)
        page_layout.addWidget(appearance_card)
        page_layout.addWidget(window_card)
        page_layout.addStretch()

    def apply_theme(self):
        theme_name = self.theme_combo.currentData()

        self.main_window.app_settings.set_theme(
            theme_name
        )
        self.main_window.app_settings.sync()

        load_theme(
            QApplication.instance(),
            theme_name,
        )

        self.main_window.statusBar().showMessage(
            f"{theme_name.title()} theme applied"
        )

    def reset_window_position(self):
        self.main_window.app_settings.clear_geometry()
        self.main_window.app_settings.sync()

        self.main_window.resize(1440, 880)
        self.main_window.move(100, 80)

        self.main_window.statusBar().showMessage(
            "Window size and position reset"
        )
