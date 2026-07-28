from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PlaceholderPage(QWidget):
    def __init__(self, title_text, description_text):
        super().__init__()

        card = QFrame()
        card.setObjectName("placeholderCard")
        card.setMaximumWidth(700)

        title = QLabel(title_text)
        title.setObjectName("placeholderTitle")
        title.setAlignment(Qt.AlignCenter)

        description = QLabel(description_text)
        description.setObjectName("placeholderDescription")
        description.setAlignment(Qt.AlignCenter)
        description.setWordWrap(True)

        button = QPushButton("Module Coming Next")
        button.setObjectName("secondaryButton")
        button.setEnabled(False)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(42, 42, 42, 42)
        card_layout.setSpacing(16)

        card_layout.addWidget(title)
        card_layout.addWidget(description)
        card_layout.addWidget(button, alignment=Qt.AlignCenter)

        page_layout = QVBoxLayout(self)
        page_layout.addStretch()
        page_layout.addWidget(card, alignment=Qt.AlignCenter)
        page_layout.addStretch()
