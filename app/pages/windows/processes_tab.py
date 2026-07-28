import csv
from datetime import datetime

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.process_service import ProcessService
from app.workers.callable_worker import CallableWorker


class NumericTableItem(QTableWidgetItem):
    def __init__(self, display_text, numeric_value):
        super().__init__(display_text)
        self.numeric_value = numeric_value

    def __lt__(self, other):
        if isinstance(other, NumericTableItem):
            return self.numeric_value < other.numeric_value

        return super().__lt__(other)


class ProcessesTab(QWidget):
    def __init__(self):
        super().__init__()

        self.service = ProcessService()
        self.processes = []
        self.auto_refresh_enabled = True
        self.refresh_thread = None
        self.refresh_worker = None
        self.pending_selected_pid = None

        self.build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(
            self.refresh_processes
        )
        self.refresh_timer.start(4000)

        QTimer.singleShot(0, self.refresh_processes)

    def build_ui(self):
        heading = QLabel("Process Manager")
        heading.setObjectName("tabHeading")

        description = QLabel(
            "View running processes, inspect details, search, "
            "sort, export, and safely end selected applications."
        )
        description.setObjectName("tabDescription")

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_layout.addWidget(heading)
        title_layout.addWidget(description)

        self.process_count_label = QLabel("0 processes")
        self.process_count_label.setObjectName("updatedLabel")

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText(
            "Search by process name, PID, user, or status..."
        )
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(
            self.apply_filter
        )

        self.auto_refresh_button = QPushButton(
            "Auto Refresh: On"
        )
        self.auto_refresh_button.setObjectName(
            "secondaryButton"
        )
        self.auto_refresh_button.clicked.connect(
            self.toggle_auto_refresh
        )

        self.export_button = QPushButton("Export CSV")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.clicked.connect(
            self.export_processes
        )

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(
            self.refresh_processes
        )

        top_actions = QHBoxLayout()
        top_actions.addWidget(self.process_count_label)
        top_actions.addStretch()
        top_actions.addWidget(self.auto_refresh_button)
        top_actions.addWidget(self.export_button)
        top_actions.addWidget(self.refresh_button)

        heading_row = QHBoxLayout()
        heading_row.addLayout(title_layout)
        heading_row.addStretch()
        heading_row.addLayout(top_actions)

        search_row = QHBoxLayout()
        search_row.addWidget(self.search_box, 1)

        self.table = QTableWidget()
        self.table.setObjectName("processTable")
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                "Process",
                "PID",
                "CPU %",
                "Memory",
                "Status",
                "User",
                "Threads",
            ]
        )

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(
            self.update_selected_process
        )
        self.table.doubleClicked.connect(
            self.show_process_details
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.Stretch,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeToContents,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeToContents,
        )
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeToContents,
        )
        header.setSectionResizeMode(
            5,
            QHeaderView.Stretch,
        )
        header.setSectionResizeMode(
            6,
            QHeaderView.ResizeToContents,
        )

        details_frame = QFrame()
        details_frame.setObjectName("processActionBar")

        self.selected_label = QLabel(
            "Select a process to view available actions."
        )
        self.selected_label.setObjectName("systemValue")

        self.details_button = QPushButton("View Details")
        self.details_button.setObjectName("secondaryButton")
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(
            self.show_process_details
        )

        self.end_button = QPushButton("End Process")
        self.end_button.setObjectName("dangerButton")
        self.end_button.setEnabled(False)
        self.end_button.clicked.connect(
            self.end_selected_process
        )

        details_layout = QHBoxLayout(details_frame)
        details_layout.setContentsMargins(14, 10, 14, 10)
        details_layout.addWidget(self.selected_label, 1)
        details_layout.addWidget(self.details_button)
        details_layout.addWidget(self.end_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addLayout(heading_row)
        layout.addLayout(search_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(details_frame)

    def refresh_processes(self):
        if self.refresh_thread is not None:
            return

        self.pending_selected_pid = self.get_selected_pid()
        self.refresh_button.setEnabled(False)

        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(
            self.service.collect_processes
        )
        self.refresh_worker.moveToThread(
            self.refresh_thread
        )

        self.refresh_thread.started.connect(
            self.refresh_worker.run
        )
        self.refresh_worker.succeeded.connect(
            self._processes_loaded
        )
        self.refresh_worker.failed.connect(
            self._processes_failed
        )
        self.refresh_worker.finished.connect(
            self.refresh_thread.quit
        )
        self.refresh_worker.finished.connect(
            self.refresh_worker.deleteLater
        )
        self.refresh_thread.finished.connect(
            self._processes_finished
        )
        self.refresh_thread.finished.connect(
            self.refresh_thread.deleteLater
        )
        self.refresh_thread.start()

    def _processes_loaded(self, processes):
        self.processes = processes
        self.populate_table(
            self.processes,
            self.pending_selected_pid,
        )
        self.apply_filter(self.search_box.text())

    def _processes_failed(self, error_message):
        QMessageBox.critical(
            self,
            "Process Manager Error",
            (
                "ARC3 could not load processes.\n\n"
                f"{error_message}"
            ),
        )

    def _processes_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_worker = None
        self.refresh_thread = None

    def populate_table(self, processes, selected_pid=None):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        selected_row = None

        for process in processes:
            row = self.table.rowCount()
            self.table.insertRow(row)

            process_name = process["name"]
            pid = process["pid"]
            cpu = process["cpu"]
            memory = process["memory_mb"]
            status = process["status"]
            username = process["username"]
            threads = process["threads"]

            name_item = QTableWidgetItem(process_name)
            name_item.setData(Qt.UserRole, pid)

            pid_item = NumericTableItem(str(pid), pid)
            cpu_item = NumericTableItem(
                f"{cpu:.1f}",
                cpu,
            )
            memory_item = NumericTableItem(
                f"{memory:.1f} MB",
                memory,
            )
            status_item = QTableWidgetItem(status)
            user_item = QTableWidgetItem(username)
            thread_item = NumericTableItem(
                str(threads),
                threads,
            )

            if cpu >= 50:
                cpu_item.setForeground(QColor("#ff6b6b"))

            if memory >= 1000:
                memory_item.setForeground(
                    QColor("#f59e0b")
                )

            if self.service.is_protected(pid, process_name):
                name_item.setToolTip(
                    "Protected system or ARC3 process"
                )

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, pid_item)
            self.table.setItem(row, 2, cpu_item)
            self.table.setItem(row, 3, memory_item)
            self.table.setItem(row, 4, status_item)
            self.table.setItem(row, 5, user_item)
            self.table.setItem(row, 6, thread_item)

            if pid == selected_pid:
                selected_row = row

        self.table.setSortingEnabled(True)

        if selected_row is not None:
            self.table.selectRow(selected_row)

    def apply_filter(self, text):
        search_text = text.strip().lower()
        visible_count = 0

        for row in range(self.table.rowCount()):
            values = []

            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)

                if item:
                    values.append(item.text().lower())

            matches = (
                not search_text
                or any(
                    search_text in value
                    for value in values
                )
            )

            self.table.setRowHidden(row, not matches)

            if matches:
                visible_count += 1

        if search_text:
            self.process_count_label.setText(
                f"{visible_count} matching processes"
            )
        else:
            self.process_count_label.setText(
                f"{len(self.processes)} processes"
            )

    def toggle_auto_refresh(self):
        self.auto_refresh_enabled = (
            not self.auto_refresh_enabled
        )

        if self.auto_refresh_enabled:
            self.refresh_timer.start(4000)
            self.auto_refresh_button.setText(
                "Auto Refresh: On"
            )
        else:
            self.refresh_timer.stop()
            self.auto_refresh_button.setText(
                "Auto Refresh: Off"
            )

    def get_selected_pid(self):
        selected_rows = self.table.selectionModel().selectedRows()

        if not selected_rows:
            return None

        row = selected_rows[0].row()
        item = self.table.item(row, 1)

        if not item:
            return None

        try:
            return int(item.text())
        except ValueError:
            return None

    def get_selected_name(self):
        selected_rows = self.table.selectionModel().selectedRows()

        if not selected_rows:
            return ""

        item = self.table.item(
            selected_rows[0].row(),
            0,
        )

        return item.text() if item else ""

    def update_selected_process(self):
        pid = self.get_selected_pid()
        process_name = self.get_selected_name()

        has_selection = pid is not None

        self.details_button.setEnabled(has_selection)

        if not has_selection:
            self.end_button.setEnabled(False)
            self.selected_label.setText(
                "Select a process to view available actions."
            )
            return

        protected = self.service.is_protected(
            pid,
            process_name,
        )

        self.end_button.setEnabled(not protected)

        if protected:
            self.selected_label.setText(
                f"Selected: {process_name} — PID {pid} "
                "(protected)"
            )
        else:
            self.selected_label.setText(
                f"Selected: {process_name} — PID {pid}"
            )

    def show_process_details(self):
        pid = self.get_selected_pid()

        if pid is None:
            return

        try:
            details = self.service.get_process_details(pid)

            detail_text = (
                f"Name: {details['name']}\n"
                f"PID: {details['pid']}\n"
                f"Status: {details['status']}\n"
                f"User: {details['username']}\n"
                f"Threads: {details['threads']}\n"
                f"Parent: {details['parent']}\n"
                f"Memory: {details['memory']}\n"
                f"CPU Time: {details['cpu_time']}\n\n"
                f"Executable:\n{details['executable']}\n\n"
                f"Command Line:\n{details['command_line']}"
            )

            box = QMessageBox(self)
            box.setWindowTitle("Process Details")
            box.setIcon(QMessageBox.Information)
            box.setText(detail_text)
            box.setStandardButtons(QMessageBox.Ok)
            box.exec()

        except Exception as error:
            QMessageBox.warning(
                self,
                "Process Unavailable",
                (
                    "The selected process may have closed or "
                    f"cannot be accessed.\n\n{error}"
                ),
            )

            self.refresh_processes()

    def end_selected_process(self):
        pid = self.get_selected_pid()
        process_name = self.get_selected_name()

        if pid is None:
            return

        if self.service.is_protected(pid, process_name):
            QMessageBox.warning(
                self,
                "Protected Process",
                "ARC3 will not terminate this protected process.",
            )
            return

        answer = QMessageBox.question(
            self,
            "End Process",
            (
                f"End {process_name}?\n\n"
                f"PID: {pid}\n\n"
                "Unsaved information in this application "
                "may be lost."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        successful, message = (
            self.service.terminate_process(pid)
        )

        if successful:
            QMessageBox.information(
                self,
                "Process Ended",
                message,
            )
        else:
            QMessageBox.warning(
                self,
                "Unable to End Process",
                message,
            )

        self.refresh_processes()

    def export_processes(self):
        default_name = (
            "ARC3_Processes_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".csv"
        )

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Process List",
            default_name,
            "CSV Files (*.csv)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".csv"):
            file_path += ".csv"

        try:
            with open(
                file_path,
                "w",
                newline="",
                encoding="utf-8",
            ) as csv_file:
                writer = csv.writer(csv_file)

                writer.writerow(
                    [
                        "Process",
                        "PID",
                        "CPU Percent",
                        "Memory MB",
                        "Status",
                        "User",
                        "Threads",
                        "Executable",
                    ]
                )

                for process in self.processes:
                    writer.writerow(
                        [
                            process["name"],
                            process["pid"],
                            process["cpu"],
                            process["memory_mb"],
                            process["status"],
                            process["username"],
                            process["threads"],
                            process["exe"],
                        ]
                    )

            QMessageBox.information(
                self,
                "Export Complete",
                f"Process list saved to:\n\n{file_path}",
            )

        except OSError as error:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"ARC3 could not save the file.\n\n{error}",
            )
