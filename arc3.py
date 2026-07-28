import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from app.main_window import MainWindow
from app.ui.phase4_enhancements import install_phase4_enhancements
from app.settings import AppSettings
from app.theme import load_theme


def main():
    app = QApplication(sys.argv)

    app.setApplicationName("ARC3")
    app.setOrganizationName("ARC3")
    app.setOrganizationDomain("arc3.local")

    settings = AppSettings()
    load_theme(app, settings.get_theme())

    app_icon = app.style().standardIcon(
        QStyle.SP_ComputerIcon
    )
    app.setWindowIcon(app_icon)

    window = MainWindow()
    install_phase4_enhancements(window)
    window.setWindowIcon(app_icon)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
