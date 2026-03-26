from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import QRegularExpression, Qt
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..version import __version__


_NETWORK_ID_RE = re.compile(r"^[0-9a-fA-F]{16}$")


class JoinNetworkDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Join New Network")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter a 16-character ZeroTier Network ID:"))

        self.network_id_edit = QLineEdit()
        self.network_id_edit.setPlaceholderText("e.g. 565799d8f620c5c5")
        self.network_id_edit.setMaxLength(16)
        self.network_id_edit.setClearButtonEnabled(True)
        self.network_id_edit.setFixedWidth(260)
        self.network_id_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # Only allow hex characters; enforce exact length via validation at accept time too.
        validator = QRegularExpressionValidator(QRegularExpression(r"[0-9a-fA-F]{0,16}"), self.network_id_edit)
        self.network_id_edit.setValidator(validator)

        layout.addWidget(self.network_id_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def network_id(self) -> str:
        return self.network_id_edit.text().strip()

    def accept(self) -> None:
        nwid = self.network_id()
        if not _NETWORK_ID_RE.match(nwid):
            QMessageBox.warning(self, "Invalid Network ID", "Network ID must be 16 hex characters (0-9, a-f).")
            return
        super().accept()


class TokenDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ZeroTier Token Required")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("The ZeroTier token could not be read from the system location."))

        layout.addWidget(
            QLabel(
                "Paste the contents of `authtoken.secret` below. This value is sensitive."
            )
        )

        self.token_edit = QTextEdit()
        self.token_edit.setPlaceholderText("Paste authtoken.secret contents here...")
        self.token_edit.setTabChangesFocus(True)
        self.token_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.token_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def token(self) -> str:
        return self.token_edit.toPlainText().strip()

    def accept(self) -> None:
        if not self.token():
            QMessageBox.warning(self, "Token required", "Please paste `authtoken.secret` contents.")
            return
        super().accept()


class ServicePromptDialog(QDialog):
    """
    Shown when the local ZeroTier service is missing/stopped.
    """

    def __init__(self, *, installed: bool, active: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ZeroTier Service")

        self.start_button: Optional[QPushButton] = None
        self.install_button: Optional[QPushButton] = None

        layout = QVBoxLayout(self)

        if not installed:
            layout.addWidget(QLabel("ZeroTier service is not installed on this system."))
        elif not active:
            layout.addWidget(QLabel("ZeroTier service is installed but not running."))
        else:
            layout.addWidget(QLabel("ZeroTier service status could not be determined."))

        layout.addWidget(
            QLabel("The GUI needs access to `http://127.0.0.1:9993` to display network status.")
        )

        btn_layout = QHBoxLayout()
        layout.addLayout(btn_layout)

        if installed:
            self.start_button = QPushButton("Start ZeroTier Service")
            btn_layout.addWidget(self.start_button)

        if not installed:
            self.install_button = QPushButton("Install ZeroTier Service")
            btn_layout.addWidget(self.install_button)

        layout.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

    def run_choice(self) -> str:
        """
        Returns 'start', 'install', or 'cancel' depending on the clicked button.
        """
        # Button handlers will set `self._choice`.
        return getattr(self, "_choice", "cancel")

    def wire_buttons(self, on_start, on_install) -> None:
        if self.start_button is not None:
            def _start():
                setattr(self, "_choice", "start")
                on_start()
                self.accept()

            self.start_button.clicked.connect(_start)

        if self.install_button is not None:
            def _install():
                setattr(self, "_choice", "install")
                on_install()
                self.accept()

            self.install_button.clicked.connect(_install)


class AboutDialog(QDialog):
    def __init__(self, github_url: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About ZeroTier GUI")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"ZeroTier GUI (Linux)\nVersion: {__version__}"))

        central = QLabel('<a href="https://central.zerotier.com">https://central.zerotier.com</a>')
        central.setOpenExternalLinks(True)
        layout.addWidget(central)

        gh = QLabel(f'<a href="{github_url}">{github_url}</a>')
        gh.setOpenExternalLinks(True)
        layout.addWidget(gh)

        layout.addWidget(QLabel("Licensed under the MIT License."))

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

