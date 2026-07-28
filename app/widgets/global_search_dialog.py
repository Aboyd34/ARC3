from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QVBoxLayout,
)


@dataclass
class SearchAction:
    title: str
    category: str
    keywords: str
    callback: Callable


class GlobalSearchDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)

        self.main_window = main_window
        self.actions = []

        self.setWindowTitle("ARC3 Search")
        self.setModal(True)
        self.resize(620, 430)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "Search ARC3 tools and pages..."
        )
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(
            self.filter_results
        )

        hint = QLabel(
            "Type to search • Enter to open • Esc to close"
        )
        hint.setObjectName("tabDescription")

        self.results = QListWidget()
        self.results.itemActivated.connect(
            self.activate_item
        )
        self.results.itemDoubleClicked.connect(
            self.activate_item
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        layout.addWidget(self.search_box)
        layout.addWidget(hint)
        layout.addWidget(self.results, 1)

        self.collect_actions()
        self.filter_results("")

    def showEvent(self, event):
        super().showEvent(event)

        self.collect_actions()
        self.filter_results("")
        self.search_box.clear()
        self.search_box.setFocus()

    def collect_actions(self):
        self.actions = []

        self.collect_sidebar_actions()
        self.collect_tab_actions()

        self.actions.append(
            SearchAction(
                "Refresh Current View",
                "Command",
                "refresh reload update f5",
                self.refresh_current_view,
            )
        )

    def collect_sidebar_actions(self):
        list_widgets = self.main_window.findChildren(
            QListWidget
        )

        for list_widget in list_widgets:
            if list_widget is self.results:
                continue

            for row in range(list_widget.count()):
                item = list_widget.item(row)

                if not item:
                    continue

                title = item.text().strip()

                if not title:
                    continue

                self.actions.append(
                    SearchAction(
                        title,
                        "Navigation",
                        title.lower(),
                        lambda lw=list_widget, r=row: (
                            lw.setCurrentRow(r)
                        ),
                    )
                )

    def collect_tab_actions(self):
        tab_widgets = self.main_window.findChildren(
            QTabWidget
        )

        for tab_widget in tab_widgets:
            for index in range(tab_widget.count()):
                title = tab_widget.tabText(index).strip()

                if not title:
                    continue

                self.actions.append(
                    SearchAction(
                        title,
                        "Windows Tool",
                        f"{title.lower()} windows tab tool",
                        lambda tw=tab_widget, i=index: (
                            tw.setCurrentIndex(i)
                        ),
                    )
                )

    def filter_results(self, text):
        search_text = text.strip().lower()

        self.results.clear()

        matching_actions = []

        for action in self.actions:
            searchable = (
                f"{action.title} "
                f"{action.category} "
                f"{action.keywords}"
            ).lower()

            if not search_text or search_text in searchable:
                matching_actions.append(action)

        matching_actions.sort(
            key=lambda action: (
                action.category,
                action.title.lower(),
            )
        )

        for action in matching_actions:
            item = QListWidgetItem(
                f"{action.title}    ·    {action.category}"
            )
            item.setData(Qt.UserRole, action)
            self.results.addItem(item)

        if self.results.count():
            self.results.setCurrentRow(0)

    def activate_item(self, item):
        if not item:
            return

        action = item.data(Qt.UserRole)

        if not action:
            return

        self.accept()
        action.callback()

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and self.results.currentItem()
        ):
            self.activate_item(
                self.results.currentItem()
            )
            return

        super().keyPressEvent(event)

    def refresh_current_view(self):
        buttons = self.main_window.findChildren(
            __import__(
                "PySide6.QtWidgets",
                fromlist=["QPushButton"],
            ).QPushButton
        )

        for button in buttons:
            if button.text().strip().lower() == "refresh":
                if button.isVisible() and button.isEnabled():
                    button.click()
                    return
