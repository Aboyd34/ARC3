from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
)


class ToastNotification(QFrame):
    def __init__(
        self,
        parent,
        message,
        duration=3500,
        notification_type="info",
    ):
        super().__init__(parent)

        self.setObjectName("toastNotification")
        self.setAttribute(Qt.WA_StyledBackground, True)

        icons = {
            "success": "✓",
            "warning": "!",
            "error": "×",
            "info": "i",
        }

        icon = QLabel(
            icons.get(notification_type, "i")
        )
        icon.setObjectName("toastIcon")

        message_label = QLabel(message)
        message_label.setObjectName("toastMessage")
        message_label.setWordWrap(True)

        close_button = QPushButton("×")
        close_button.setObjectName("toastCloseButton")
        close_button.setFixedSize(26, 26)
        close_button.clicked.connect(self.close)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 10, 11)
        layout.setSpacing(10)

        layout.addWidget(icon)
        layout.addWidget(message_label, 1)
        layout.addWidget(close_button)

        self.setMinimumWidth(320)
        self.setMaximumWidth(480)

        self.setStyleSheet(
            """
            QFrame#toastNotification {
                background-color: #20252e;
                border: 1px solid #3a4250;
                border-radius: 10px;
            }

            QLabel#toastIcon {
                font-size: 17px;
                font-weight: 700;
                color: #60a5fa;
            }

            QLabel#toastMessage {
                color: #f3f4f6;
                font-size: 12px;
            }

            QPushButton#toastCloseButton {
                background: transparent;
                border: none;
                color: #aab2c0;
                font-size: 17px;
                font-weight: 700;
            }

            QPushButton#toastCloseButton:hover {
                color: white;
                background-color: #343b48;
                border-radius: 5px;
            }
            """
        )

        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

        QTimer.singleShot(duration, self.close)

    def reposition(self):
        if not self.parent():
            return

        margin = 20

        x_position = (
            self.parent().width()
            - self.width()
            - margin
        )

        status_bar_height = 0

        if hasattr(self.parent(), "statusBar"):
            status_bar = self.parent().statusBar()

            if status_bar:
                status_bar_height = status_bar.height()

        y_position = (
            self.parent().height()
            - self.height()
            - status_bar_height
            - margin
        )

        self.move(
            max(margin, x_position),
            max(margin, y_position),
        )


def show_toast(
    parent,
    message,
    notification_type="info",
    duration=3500,
):
    toast = ToastNotification(
        parent,
        message,
        duration,
        notification_type,
    )

    if not hasattr(parent, "_arc3_toasts"):
        parent._arc3_toasts = []

    parent._arc3_toasts.append(toast)

    toast.destroyed.connect(
        lambda: _remove_toast(parent, toast)
    )

    return toast


def _remove_toast(parent, toast):
    if not hasattr(parent, "_arc3_toasts"):
        return

    try:
        parent._arc3_toasts.remove(toast)
    except ValueError:
        pass
