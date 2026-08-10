"""Local-only ARC3 Connectivity pairing and trust management page."""

from __future__ import annotations

import json

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app.connectivity.pairing import PairingError, PairingRequest
from app.connectivity.pairing_service import PairingService
from app.connectivity.runtime import (
    connectivity_data_directory, create_health_transport, create_pairing_service,
)
from app.connectivity.transport import private_ipv4_interfaces
from app.workers.callable_worker import CallableWorker


class ConnectivityPage(QWidget):
    def __init__(self, main_window=None, pairing_service: PairingService | None = None):
        super().__init__()
        self.main_window = main_window
        self.service = pairing_service
        self.service_thread = None
        self.service_worker = None
        self.transport = None
        self.setObjectName("connectivityPage")
        self._build_interface()
        if self.service is None:
            self._set_service_available(False)
            QTimer.singleShot(0, self._start_service_load)
        else:
            self.refresh()

    def _build_interface(self):
        title = QLabel("Connectivity")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Approve signed devices locally before allowing read-only ARC3 access."
        )
        subtitle.setObjectName("pageSubtitle")

        self.identity_label = QLabel()
        self.identity_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.identity_label.setWordWrap(True)

        self.request_input = QPlainTextEdit()
        self.request_input.setPlaceholderText("Paste a signed pairing-request JSON envelope here...")
        self.request_input.setMaximumHeight(130)
        self.receive_button = QPushButton("Receive Signed Request")
        self.receive_button.clicked.connect(self.receive_request)

        receive_card = QFrame()
        receive_card.setObjectName("wideCard")
        receive_layout = QVBoxLayout(receive_card)
        receive_layout.addWidget(QLabel("LOCAL DEVICE IDENTITY"))
        receive_layout.addWidget(self.identity_label)
        receive_layout.addWidget(self.request_input)
        receive_layout.addWidget(self.receive_button, 0, Qt.AlignRight)

        self.lan_checkbox = QCheckBox("Allow connections from the private LAN")
        self.lan_address = QComboBox()
        self.lan_address.addItems(private_ipv4_interfaces())
        self.lan_address.setEnabled(False)
        self.lan_checkbox.toggled.connect(self.lan_address.setEnabled)
        self.listener_status = QLabel("Remote health listener: Stopped")
        self.listener_status.setObjectName("connectionStatus")
        self.listener_button = QPushButton("Start Listener")
        self.listener_button.clicked.connect(self.toggle_listener)
        listener_row = QHBoxLayout()
        listener_row.addWidget(self.listener_status)
        listener_row.addStretch()
        listener_row.addWidget(self.lan_checkbox)
        listener_row.addWidget(self.lan_address)
        listener_row.addWidget(self.listener_button)
        receive_layout.addLayout(listener_row)

        self.pending_list = QListWidget()
        self.pending_list.setSelectionMode(QListWidget.SingleSelection)
        self.pending_list.currentItemChanged.connect(self._selection_changed)
        self.trusted_list = QListWidget()

        self.health_permission = QCheckBox("Allow read-only system health")
        self.health_permission.setChecked(True)
        self.approve_button = QPushButton("Approve Selected")
        self.approve_button.clicked.connect(self.approve_selected)
        self.reject_button = QPushButton("Reject Selected")
        self.reject_button.clicked.connect(self.reject_selected)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        actions = QHBoxLayout()
        actions.addWidget(self.health_permission)
        actions.addStretch()
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.reject_button)
        actions.addWidget(self.approve_button)

        pending_panel = QFrame()
        pending_panel.setObjectName("wideCard")
        pending_layout = QVBoxLayout(pending_panel)
        pending_layout.addWidget(QLabel("PENDING PAIRING REQUESTS"))
        pending_layout.addWidget(self.pending_list)
        pending_layout.addLayout(actions)

        trusted_panel = QFrame()
        trusted_panel.setObjectName("wideCard")
        trusted_layout = QVBoxLayout(trusted_panel)
        trusted_layout.addWidget(QLabel("TRUSTED DEVICES"))
        trusted_layout.addWidget(self.trusted_list)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(pending_panel)
        splitter.addWidget(trusted_panel)
        splitter.setSizes([650, 450])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(receive_card)
        layout.addWidget(splitter, 1)

    def refresh(self):
        if self.service is None:
            return
        identity = self.service.approver_provider.identity(self.service.approver_name)
        self.identity_label.setText(
            f"{identity.name}\nFingerprint: {identity.device_id}"
        )
        self.pending_list.clear()
        for request in self.service.pending_store.list():
            item = QListWidgetItem(
                f"{request.device.name}\n{request.device.device_id}\nRequest {request.request_id}"
            )
            item.setData(Qt.UserRole, request.request_id)
            self.pending_list.addItem(item)
        self.trusted_list.clear()
        for device in self.service.trusted_store.list():
            permissions = ", ".join(device.permissions) or "No permissions"
            self.trusted_list.addItem(
                f"{device.name}\n{device.device_id}\nPermissions: {permissions}"
            )
        self._selection_changed(self.pending_list.currentItem())

    def _start_service_load(self):
        if self.service is not None or self.service_thread is not None:
            return
        self.identity_label.setText("Loading protected ARC3 identity...")
        self.service_thread = QThread(self)
        self.service_worker = CallableWorker(create_pairing_service)
        self.service_worker.moveToThread(self.service_thread)
        self.service_thread.started.connect(self.service_worker.run)
        self.service_worker.succeeded.connect(self._service_loaded)
        self.service_worker.failed.connect(self._service_failed)
        self.service_worker.finished.connect(self.service_thread.quit)
        self.service_worker.finished.connect(self.service_worker.deleteLater)
        self.service_thread.finished.connect(self._service_finished)
        self.service_thread.finished.connect(self.service_thread.deleteLater)
        self.service_thread.start()

    def _service_loaded(self, service):
        self.service = service
        self._set_service_available(True)
        self.refresh()
        if service.recovery_error:
            self._status(service.recovery_error)

    def _service_failed(self, message):
        self.identity_label.setText("Connectivity identity unavailable")
        self._status(f"Connectivity initialization failed: {message}")

    def _service_finished(self):
        self.service_worker = None
        self.service_thread = None

    def _set_service_available(self, available):
        for widget in (
            self.receive_button, self.listener_button, self.refresh_button,
            self.health_permission, self.approve_button, self.reject_button,
        ):
            widget.setEnabled(available)

    def receive_request(self):
        if self.service is None:
            return
        text = self.request_input.toPlainText().strip()
        if not text:
            self._status("Paste a signed pairing request first.")
            return
        try:
            request = PairingRequest.from_dict(json.loads(text))
            result = self.service.receive(request)
        except (json.JSONDecodeError, PairingError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid Pairing Request", str(exc))
            return
        self._status(result.message)
        if result.success:
            self.request_input.clear()
        self.refresh()

    def toggle_listener(self):
        if self.service is None:
            return
        if self.transport is not None and self.transport.running:
            self.transport.stop()
            self.transport = None
            self.listener_status.setText("Remote health listener: Stopped")
            self.listener_button.setText("Start Listener")
            self.lan_checkbox.setEnabled(True)
            self._status("ARC3 Connectivity listener stopped.")
            return
        allow_lan = self.lan_checkbox.isChecked()
        lan_host = None
        if allow_lan:
            lan_host = self.lan_address.currentText().strip()
            if not lan_host:
                QMessageBox.warning(
                    self, "No Private-LAN Address",
                    "No private-LAN interface is available for the listener.",
                )
                return
            answer = QMessageBox.question(
                self, "Enable Private-LAN Listener",
                f"Allow trusted devices to contact ARC3 at {lan_host} on TCP port 8766?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            tls_directory = connectivity_data_directory() / "tls"
            self.transport = create_health_transport(
                self.service,
                allow_private_lan=allow_lan,
                host=lan_host if allow_lan else "127.0.0.1",
                tls_certfile=(tls_directory / "server.crt") if allow_lan else None,
                tls_keyfile=(tls_directory / "server.key") if allow_lan else None,
            )
            self.transport.start()
        except (OSError, RuntimeError, ValueError) as exc:
            self.transport = None
            QMessageBox.warning(self, "Listener Failed", str(exc))
            return
        scope = "Private LAN" if allow_lan else "This PC only"
        self.listener_status.setText(f"Remote health listener: Running · {scope} · TCP 8766")
        self.listener_button.setText("Stop Listener")
        self.lan_checkbox.setEnabled(False)
        self.lan_address.setEnabled(False)
        self._status(f"ARC3 Connectivity listener started for {scope.lower()}.")

    def approve_selected(self):
        if self.service is None:
            return
        request_id = self._selected_request_id()
        if request_id is None:
            return
        permissions = ("health.read",) if self.health_permission.isChecked() else ()
        answer = QMessageBox.question(
            self, "Approve Device",
            "Trust this device with the selected permissions?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.approve(request_id, permissions)
        except PairingError as exc:
            QMessageBox.warning(self, "Approval Failed", str(exc))
            return
        self._status("Device approved and added to trusted devices.")
        self.refresh()

    def reject_selected(self):
        if self.service is None:
            return
        request_id = self._selected_request_id()
        if request_id is None:
            return
        answer = QMessageBox.question(
            self, "Reject Pairing Request", "Reject this pending pairing request?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._status(self.service.reject(request_id).message)
        self.refresh()

    def _selected_request_id(self):
        item = self.pending_list.currentItem()
        if item is None:
            self._status("Select a pending pairing request first.")
            return None
        return item.data(Qt.UserRole)

    def _selection_changed(self, item, previous=None):
        enabled = item is not None
        self.approve_button.setEnabled(enabled)
        self.reject_button.setEnabled(enabled)

    def _status(self, message):
        if self.main_window is not None and self.main_window.statusBar() is not None:
            self.main_window.statusBar().showMessage(message, 6000)

    def shutdown(self):
        if self.transport is not None:
            self.transport.stop()
            self.transport = None

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
