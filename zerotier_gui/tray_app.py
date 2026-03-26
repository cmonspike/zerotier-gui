from __future__ import annotations

import time
from typing import Any, Optional

import logging
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import (
    QColor,
    QAction,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from .api import (
    APIError,
    ServiceNotReachableError,
    TokenMissingError,
    TokenPermissionError,
    NetworkPermissionPayload,
    ZeroTierAPI,
)
from .autostart import is_autostart_enabled, set_autostart_enabled
from .network_store import forget_network, list_known_networks, remember_network
from .service import ZeroTierServiceManager
from .ui.dialogs import AboutDialog, JoinNetworkDialog, ServicePromptDialog, TokenDialog
from .ui.networks_window import NetworksWindow


class TrayApp:
    """
    Tray-only ZeroTier GUI.

    UI is rebuilt from live `/network` data whenever polling updates.
    """

    def __init__(self, qt_app: QApplication) -> None:
        self._log = self._setup_logging()
        self.app = qt_app
        self.api = ZeroTierAPI()
        self.service_mgr = ZeroTierServiceManager()

        self._poll_timer = QTimer()
        self._poll_timer.setInterval(4000)
        self._poll_timer.timeout.connect(self.refresh)

        self._menu: Optional[QMenu] = None
        self._status_menu: Optional[QMenu] = None
        self._active_popup_menu: Optional[QMenu] = None
        self._menu_open = False
        self._tray = QSystemTrayIcon()
        self._tray.activated.connect(self._on_activated)

        self._token_prompt_shown = False
        self._privileged_token_import_attempted = False
        self._service_prompt_shown = False
        self._updating_network = False
        self._last_networks: dict[str, dict[str, Any]] = {}
        self._last_api_error: Optional[str] = None
        self._last_api_error_at: float = 0.0

        self._build_tray_icon(connected=False)
        self._tray.setVisible(True)

        self._poll_timer.start()
        self.refresh()
        try:
            self._log.info("TrayApp started")
        except Exception:
            pass

    def show(self) -> None:
        self._tray.setVisible(True)
        self._tray.show()

    @staticmethod
    def _setup_logging() -> logging.Logger:
        log_dir = Path.home() / ".config" / "zerotier-gui"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "zerotier-gui.log"

        logger = logging.getLogger("zerotier-gui")
        if logger.handlers:
            return logger

        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        return logger

    def _build_tray_icon(self, *, connected: bool) -> None:
        # Create a small pixmap version of the official orange icon.
        # The ZeroTier artwork uses a rounded square + the ⌁ glyph (U+23C1) in orange.
        size = 24
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        orange = QColor("#ffb354")
        painter.setBrush(orange)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(1, 1, size - 2, size - 2, 6, 6)

        # Glyph
        painter.setPen(QColor("#000000"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(18)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "\u23C1")

        # Overlay connection status.
        overlay_color = QColor("#2ecc71") if connected else QColor("#e74c3c")
        painter.setBrush(overlay_color)
        painter.drawEllipse(size - 9, size - 9, 8, 8)

        painter.end()

        self._tray.setIcon(QIcon(pix))
        self._tray.setToolTip("ZeroTier UI")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left click: compact status menu.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_popup_menu(self._status_menu)
            return

        # Right click/context click: full actions menu.
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self._toggle_popup_menu(self._menu)
            return

    def _toggle_popup_menu(self, menu: Optional[QMenu]) -> None:
        if menu is None:
            return
        if menu.isVisible():
            menu.close()
            return
        if self._active_popup_menu is not None and self._active_popup_menu is not menu:
            self._active_popup_menu.close()
        self._active_popup_menu = menu
        menu.popup(self._cursor_pos())

    @staticmethod
    def _cursor_pos():
        # Imported lazily to avoid extra QtGui imports in some environments.
        from PyQt6.QtGui import QCursor

        return QCursor.pos()

    def _wire_menu_lifecycle(self, menu: QMenu) -> None:
        menu.aboutToShow.connect(lambda: self._set_menu_open(True))
        menu.aboutToHide.connect(lambda: self._set_menu_open(False))

    def _set_menu_open(self, is_open: bool) -> None:
        self._menu_open = is_open
        if not is_open:
            self._active_popup_menu = None
            # Rebuild after menu event processing completes. Re-entering refresh()
            # during menu close signals can destabilize some tray backends.
            self._request_refresh()

    def _request_refresh(self) -> None:
        QTimer.singleShot(0, self.refresh)

    def _set_menu(self, menu: QMenu) -> None:
        self._wire_menu_lifecycle(menu)
        self._menu = menu

    def _set_status_menu(self, menu: QMenu) -> None:
        self._wire_menu_lifecycle(menu)
        self._status_menu = menu

    def _show_message(self, title: str, message: str) -> None:
        QMessageBox.critical(None, title, message)

    def _ensure_token_loaded(self) -> bool:
        """
        Ensure API token is available.
        Returns True if token is ready, False otherwise.
        """

        if self.api.token_loaded:
            return True

        # Try system token first, then a user override.
        try:
            self.api.load_token()
            return True
        except TokenPermissionError:
            # Try user token override first; if absent, prompt the user.
            if self.api.load_user_token():
                return True
            if not self._privileged_token_import_attempted:
                self._privileged_token_import_attempted = True
                if self.api.import_system_token_with_privilege() and self.api.load_user_token():
                    return True
            if self._token_prompt_shown:
                return False

            self._token_prompt_shown = True
            dlg = TokenDialog()
            if dlg.exec() == dlg.DialogCode.Accepted:
                self.api.set_user_token(dlg.token())
                return True
            return False
        except TokenMissingError:
            if self.api.load_user_token():
                return True
            if not self._privileged_token_import_attempted:
                self._privileged_token_import_attempted = True
                if self.api.import_system_token_with_privilege() and self.api.load_user_token():
                    return True
            if self._token_prompt_shown:
                return False

            self._token_prompt_shown = True
            dlg = TokenDialog()
            if dlg.exec() == dlg.DialogCode.Accepted:
                self.api.set_user_token(dlg.token())
                return True
            return False

    def refresh(self) -> None:
        """
        Poll `/network` and rebuild the tray menu.
        """
        try:
            # Always rebuild a minimal menu while we're starting up.
            if self._menu is None:
                self._set_menu(QMenu())
            if self._status_menu is None:
                self._set_status_menu(QMenu())

            if self._updating_network:
                return
            if self._menu_open:
                return

            if not self._ensure_token_loaded():
                fallback_networks: list[dict[str, Any]] = []
                self._set_menu(self._build_menu(service_ok=False, my_address="(token unavailable)", networks=fallback_networks))
                self._set_status_menu(self._build_status_menu(my_address="(token unavailable)", networks=fallback_networks))
                self._build_tray_icon(connected=False)
                self._tray.setVisible(True)
                self._tray.show()
                return

            # Poll service.
            try:
                live_networks = self.api.list_networks()
            except ServiceNotReachableError:
                fallback_networks = []
                self._set_menu(self._build_menu(service_ok=False, my_address="(service not running)", networks=fallback_networks))
                self._set_status_menu(self._build_status_menu(my_address="(service not running)", networks=fallback_networks))
                self._build_tray_icon(connected=False)
                self._tray.setVisible(True)
                self._tray.show()

                if not self._service_prompt_shown:
                    self._service_prompt_shown = True
                    self._prompt_service()
                return
            except APIError as e:
                fallback_networks = []
                self._set_menu(self._build_menu(service_ok=False, my_address="(API error)", networks=fallback_networks))
                self._set_status_menu(self._build_status_menu(my_address="(API error)", networks=fallback_networks))
                self._build_tray_icon(connected=False)
                self._tray.setVisible(True)
                self._tray.show()

                # Avoid message-box spam during polling.
                now = time.monotonic()
                msg = str(e)
                if msg != self._last_api_error or (now - self._last_api_error_at) > 15.0:
                    self._last_api_error = msg
                    self._last_api_error_at = now
                    self._show_message("ZeroTier API Error", msg)
                return

            self._service_prompt_shown = False
            self._token_prompt_shown = False

            for n in live_networks:
                if isinstance(n, dict):
                    remember_network(n)

            known_map = {
                str(n.get("id")): n
                for n in list_known_networks()
                if isinstance(n, dict) and n.get("id")
            }
            live_map = {
                str(n.get("id")): n
                for n in live_networks
                if isinstance(n, dict) and n.get("id")
            }
            networks: list[dict[str, Any]] = list(live_map.values())
            for nwid, known in known_map.items():
                if nwid in live_map:
                    continue
                networks.append(
                    {
                        "id": nwid,
                        "name": known.get("name") or nwid,
                        "status": "DISCONNECTED",
                        "assignedAddresses": [],
                        "allowManaged": bool(known.get("allowManaged", True)),
                        "allowGlobal": bool(known.get("allowGlobal", False)),
                        "allowDefault": bool(known.get("allowDefault", False)),
                        "allowDNS": bool(known.get("allowDNS", False)),
                        "__known_only": True,
                    }
                )

            self._last_networks = {n.get("id"): n for n in networks if isinstance(n, dict) and n.get("id")}

            my_address = self._compute_my_address(networks)
            any_connected = any(n.get("status") == "OK" for n in networks if isinstance(n, dict))

            self._set_menu(self._build_menu(service_ok=True, my_address=my_address, networks=networks))
            self._set_status_menu(self._build_status_menu(my_address=my_address, networks=networks))
            self._build_tray_icon(connected=any_connected)
            self._tray.setVisible(True)
            self._tray.show()
        except Exception:
            self._log.exception("Unexpected error in tray refresh()")

        # (rest of method moved into try-block)

    def _compute_my_address(self, networks: list[dict[str, Any]]) -> str:
        # macOS client shows a managed address (10.x.x.x) as "My Address:"
        # Choose a primary managed IP: prefer any connected network.
        connected = [n for n in networks if n.get("status") == "OK" and n.get("assignedAddresses")]
        pool = connected if connected else [n for n in networks if n.get("assignedAddresses")]
        if not pool:
            return "(no managed address)"

        first = pool[0]
        assigned = first.get("assignedAddresses") or []
        if not assigned:
            return "(no managed address)"
        return str(assigned[0])

    def _prompt_service(self) -> None:
        state = self.service_mgr.get_state()
        dlg = ServicePromptDialog(installed=state.installed, active=state.active)

        def _start():
            ok, msg = self.service_mgr.start_service()
            if not ok:
                self._show_message("Start Failed", msg)

        def _install():
            ok, msg = self.service_mgr.install_service()
            if not ok:
                self._show_message("Install Failed", msg)

        dlg.wire_buttons(on_start=_start, on_install=_install)

        # Modal prompt; after user action, refresh shortly.
        dlg.exec()
        self.refresh()

    def _build_menu(self, *, service_ok: bool, my_address: str, networks: list[dict[str, Any]]) -> QMenu:
        menu = QMenu()
        menu.setTitle("ZeroTier UI")

        # If service is down, offer quick actions (mirrors prompt).
        if not service_ok:
            menu.addSeparator()
            state = self.service_mgr.get_state()
            if state.installed and not state.active:
                a_start = QAction("Start ZeroTier Service", menu)
                a_start.triggered.connect(lambda _checked=False: self._start_service_and_refresh())
                menu.addAction(a_start)
            if not state.installed:
                a_install = QAction("Install ZeroTier Service", menu)
                a_install.triggered.connect(lambda _checked=False: self._install_service_and_refresh())
                menu.addAction(a_install)
            # Continue with rest disabled.

        if networks:
            menu.addSeparator()
        else:
            menu.addSeparator()

        # Joined networks list.
        if networks:
            for n in sorted(networks, key=lambda x: str(x.get("name") or x.get("id") or "")):
                network_id = str(n.get("id", ""))
                name = str(n.get("name") or network_id or "(unnamed)")
                status = str(n.get("status") or "")
                connected = status == "OK"

                # Keep a visible checkable top-level action for compatibility with
                # desktop environments where addMenu() rows may not render reliably
                # in tray context menus.
                label = name
                details = self._build_network_details_submenu(n)
                act = QAction(label, menu)
                act.setCheckable(True)
                act.setChecked(connected)
                act.triggered.connect(
                    lambda checked=False, nwid=network_id: self._toggle_network_connected(nwid, bool(checked))
                )
                act.setMenu(details)
                menu.addAction(act)
        else:
            a_none = QAction("No joined networks", menu)
            a_none.setEnabled(False)
            menu.addAction(a_none)

        menu.addSeparator()

        # Join New Network...
        a_join = QAction("Join New Network...", menu)
        a_join.setEnabled(True)
        a_join.triggered.connect(lambda _checked=False: self._request_join_new_network())
        menu.addAction(a_join)

        # Start UI at Login (toggle)
        a_login = QAction("Start UI at Login", menu)
        a_login.setCheckable(True)
        a_login.setChecked(is_autostart_enabled())
        a_login.triggered.connect(lambda checked: set_autostart_enabled(bool(checked)))
        menu.addAction(a_login)

        # ZeroTier Central
        a_central = QAction("ZeroTier Central", menu)
        a_central.triggered.connect(lambda _checked=False: QDesktopServices.openUrl(QUrl("https://central.zerotier.com")))
        menu.addAction(a_central)

        # Bonus power window (user-initiated, tray remains primary)
        a_show_networks = QAction("Show Networks...", menu)
        a_show_networks.triggered.connect(
            lambda _checked=False: NetworksWindow(self.api, on_updated=self._request_refresh).exec()
        )
        menu.addAction(a_show_networks)

        menu.addSeparator()

        # About (place just before Quit)
        a_about = QAction("About ZeroTier GUI", menu)
        a_about.triggered.connect(lambda _checked=False: AboutDialog("https://github.com/cmonspike/zerotier-gui").exec())
        menu.addAction(a_about)

        # Quit
        a_quit = QAction("Quit ZeroTier UI", menu)
        a_quit.triggered.connect(self._quit)
        menu.addAction(a_quit)

        return menu

    def _build_status_menu(self, *, my_address: str, networks: list[dict[str, Any]]) -> QMenu:
        menu = QMenu()
        menu.setTitle("ZeroTier Status")

        connected_networks = [
            n for n in networks if isinstance(n, dict) and str(n.get("status") or "") == "OK"
        ]
        if connected_networks:
            for n in sorted(connected_networks, key=lambda x: str(x.get("name") or x.get("id") or "")):
                name = str(n.get("name") or n.get("id") or "(unnamed)")
                menu.addAction(self._disabled_info_action(menu, f"Connected: {name}"))
                for ip in (n.get("assignedAddresses") or []):
                    menu.addAction(self._disabled_info_action(menu, f"  IP: {ip}"))
        else:
            menu.addAction(self._disabled_info_action(menu, "No connected networks"))

        menu.addSeparator()
        a_refresh = QAction("Refresh", menu)
        a_refresh.triggered.connect(lambda _checked=False: self._request_refresh())
        menu.addAction(a_refresh)
        return menu

    def _quit(self) -> None:
        # Some tray backends keep the icon visible until hidden explicitly.
        try:
            self._tray.setVisible(False)
            self._tray.hide()
        except Exception:
            pass
        QApplication.quit()

    def _join_new_network(self) -> None:
        dlg = JoinNetworkDialog()
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        network_id = dlg.network_id()

        try:
            # Default to the same checkbox state as the official client:
            # Managed addresses enabled; global/default/DNS disabled.
            payload = NetworkPermissionPayload(
                allowManaged=True,
                allowGlobal=False,
                allowDefault=False,
                allowDNS=False,
            ).to_api_dict()
            self.api.join_or_update_network(network_id, payload)
            self.refresh()
        except Exception as e:
            self._show_message("Join Failed", str(e))

    def _request_join_new_network(self) -> None:
        # Open modal dialog on next event-loop tick instead of directly from a
        # tray-menu action callback, which can crash on some Linux tray hosts.
        QTimer.singleShot(0, self._join_new_network)

    def _build_network_details_submenu(self, network: dict[str, Any]) -> QMenu:
        submenu = QMenu()
        nwid = str(network.get("id") or "")

        # Network ID (copyable)
        a_id = QAction(f"Network ID: {nwid}", submenu)
        a_id.triggered.connect(lambda _checked=False: self._copy_to_clipboard(nwid))
        submenu.addAction(a_id)

        submenu.addSeparator()

        # Four checkboxes in the exact macOS order.
        perm_actions: list[tuple[str, str]] = [
            ("allowManaged", "Allow Managed Addresses"),
            ("allowGlobal", "Allow Assignment of Global IPs"),
            ("allowDefault", "Allow Default Router Override"),
            ("allowDNS", "Allow DNS Configuration"),
        ]

        for key, label in perm_actions:
            act = QAction(label, submenu)
            act.setCheckable(True)
            act.setChecked(bool(network.get(key)))
            # Use triggered(checked) so we get the post-click value reliably.
            act.triggered.connect(lambda checked=False, k=key: self._set_network_permission(nwid, k, bool(checked)))
            submenu.addAction(act)

        submenu.addSeparator()

        # Interface info and status.
        port_dev = network.get("portDeviceName") or "-"
        nw_type = network.get("type") or "-"
        status = network.get("status") or "-"
        submenu.addAction(self._disabled_info_action(submenu, f"Interface: {port_dev}"))
        submenu.addAction(self._disabled_info_action(submenu, f"Type: {nw_type}"))
        submenu.addAction(self._disabled_info_action(submenu, f"Status: {status}"))

        # Managed IPs list.
        assigned = network.get("assignedAddresses") or []
        submenu.addSeparator()
        if assigned:
            submenu.addAction(self._disabled_info_action(submenu, "Managed IPs:"))
            for ip in assigned:
                ip = str(ip)
                a_ip = QAction(ip, submenu)
                a_ip.triggered.connect(lambda _checked=False, value=ip: self._copy_to_clipboard(value))
                submenu.addAction(a_ip)
        else:
            submenu.addAction(self._disabled_info_action(submenu, "No managed IPs assigned"))

        submenu.addSeparator()

        # Disconnect
        a_disc = QAction("Disconnect", submenu)
        a_disc.triggered.connect(lambda _checked=False: self._disconnect_network(nwid))
        submenu.addAction(a_disc)

        a_remove = QAction("Remove Network", submenu)
        a_remove.triggered.connect(lambda _checked=False: self._remove_network(nwid))
        submenu.addAction(a_remove)

        return submenu

    def _disabled_info_action(self, parent_menu: QMenu, text: str) -> QAction:
        a = QAction(text, parent_menu)
        a.setEnabled(False)
        return a

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _set_network_permission(self, network_id: str, field: str, value: bool) -> None:
        """
        Update the four permission flags via POST /network/<id>.
        """
        try:
            self._log.info("Permission toggle requested: network=%s field=%s value=%s", network_id, field, value)
        except Exception:
            pass
        current = self._last_networks.get(network_id)
        if not current:
            try:
                self._log.warning("Permission toggle aborted: network_id not in last_networks: %s", network_id)
            except Exception:
                pass
            return

        try:
            self._updating_network = True
            # The local controller expects the permission booleans. Sending only the
            # four keys improves compatibility with the official macOS client behavior.
            payload_flags = {
                "allowManaged": bool(current.get("allowManaged", False)),
                "allowGlobal": bool(current.get("allowGlobal", False)),
                "allowDefault": bool(current.get("allowDefault", False)),
                "allowDNS": bool(current.get("allowDNS", False)),
            }
            payload_flags[field] = bool(value)

            payload = NetworkPermissionPayload(
                allowManaged=payload_flags["allowManaged"],
                allowGlobal=payload_flags["allowGlobal"],
                allowDefault=payload_flags["allowDefault"],
                allowDNS=payload_flags["allowDNS"],
            ).to_api_dict()

            self.api.join_or_update_network(network_id, payload)
            try:
                self._log.info("Permission toggle POST ok: network=%s payload=%s", network_id, payload)
            except Exception:
                pass
        except Exception as e:
            self._show_message("Update Failed", str(e))
            try:
                self._log.exception("Permission update failed", exc_info=e)
            except Exception:
                pass
        finally:
            self._updating_network = False
            self._request_refresh()

    def _toggle_network_connected(self, network_id: str, checked: bool) -> None:
        """
        Top-level network checkbox behavior:
        - checked=False: leave network (disconnect)
        - checked=True: (re)join/update using current permission flags
        """
        current = self._last_networks.get(network_id)
        if current is None:
            self._request_refresh()
            return

        if not checked:
            self._disconnect_network(network_id, confirm=False)
            return

        try:
            self._updating_network = True
            payload = NetworkPermissionPayload(
                allowManaged=bool(current.get("allowManaged", True)),
                allowGlobal=bool(current.get("allowGlobal", False)),
                allowDefault=bool(current.get("allowDefault", False)),
                allowDNS=bool(current.get("allowDNS", False)),
            ).to_api_dict()
            self.api.join_or_update_network(network_id, payload)
        except Exception as e:
            self._show_message("Connect Failed", str(e))
        finally:
            self._updating_network = False
            self._request_refresh()

    def _disconnect_network(self, network_id: str, *, confirm: bool = True) -> None:
        if confirm:
            reply = QMessageBox.question(
                None,
                "Disconnect Network",
                f"Disconnect from network {network_id}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            self._updating_network = True
            self.api.leave_network(network_id)
        except Exception as e:
            self._show_message("Disconnect Failed", str(e))
        finally:
            self._updating_network = False
            self._request_refresh()

    def _remove_network(self, network_id: str) -> None:
        current = self._last_networks.get(network_id) or {}
        connected = str(current.get("status") or "") == "OK"
        if connected:
            reply = QMessageBox.question(
                None,
                "Remove Network",
                f"Remove network {network_id}? This will disconnect it.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._disconnect_network(network_id, confirm=False)

        forget_network(network_id)
        self._request_refresh()

    def _start_service_and_refresh(self) -> None:
        ok, msg = self.service_mgr.start_service()
        if not ok:
            self._show_message("Start Failed", msg)
        self.refresh()

    def _install_service_and_refresh(self) -> None:
        ok, msg = self.service_mgr.install_service()
        if not ok:
            self._show_message("Install Failed", msg)
        self.refresh()

