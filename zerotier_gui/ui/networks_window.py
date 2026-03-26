from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from ..api import APIError, ZeroTierAPI
from ..network_store import forget_network, list_known_networks, remember_network


class NetworksWindow(QDialog):
    def __init__(self, api: ZeroTierAPI, parent=None, on_updated=None) -> None:
        super().__init__(parent)
        self.api = api
        self.on_updated = on_updated
        self.setWindowTitle("ZeroTier Networks")
        self.resize(720, 560)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        layout.addLayout(top)

        self.status_label = QLabel("Fetching status...")
        top.addWidget(self.status_label, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)

        remove_btn = QPushButton("Remove Selected Network")
        remove_btn.clicked.connect(self.remove_selected_network)
        top.addWidget(remove_btn)

        # Networks
        layout.addWidget(QLabel("Joined Networks"))
        self.networks_tree = QTreeWidget()
        self.networks_tree.setColumnCount(5)
        self.networks_tree.setHeaderLabels(["Name", "Network ID", "Status", "Interface", "Managed IPs"])
        self.networks_tree.setRootIsDecorated(False)
        layout.addWidget(self.networks_tree, 3)

        # Peers
        layout.addWidget(QLabel("Peers"))
        self.peers_tree = QTreeWidget()
        self.peers_tree.setColumnCount(4)
        self.peers_tree.setHeaderLabels(["Address", "Role", "Latency(ms)", "Paths"])
        self.peers_tree.setRootIsDecorated(False)
        layout.addWidget(self.peers_tree, 2)

        self.refresh()

    def refresh(self) -> None:
        try:
            live_networks = self.api.list_networks()
            peers = self.api.list_peers()
        except APIError as e:
            QMessageBox.critical(self, "API Error", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

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
        networks = list(live_map.values())
        for nwid, known in known_map.items():
            if nwid in live_map:
                continue
            networks.append(
                {
                    "id": nwid,
                    "name": known.get("name") or nwid,
                    "status": "DISCONNECTED",
                    "portDeviceName": "-",
                    "assignedAddresses": [],
                }
            )

        self.networks_tree.clear()
        for n in sorted(networks, key=lambda x: str(x.get("name") or x.get("id") or "")):
            network_id = str(n.get("id") or "")
            name = str(n.get("name") or network_id)
            status = str(n.get("status") or "")
            iface = str(n.get("portDeviceName") or "-")
            ips = ", ".join(n.get("assignedAddresses") or [])

            item = QTreeWidgetItem([name, network_id, status, iface, ips])
            self.networks_tree.addTopLevelItem(item)

        self.peers_tree.clear()
        max_peers = 200
        for p in peers[:max_peers]:
            addr = str(p.get("address") or "")
            role = str(p.get("role") or "")
            latency = str(p.get("latency") or "")
            # Show a short list of active path endpoints.
            paths = []
            for path in p.get("paths") or []:
                if path.get("active"):
                    paths.append(str(path.get("address") or ""))
            paths_text = ", ".join([x for x in paths if x])[:200]
            item = QTreeWidgetItem([addr, role, latency, paths_text])
            self.peers_tree.addTopLevelItem(item)

        self.status_label.setText(f"Networks: {len(networks)} | Peers: {len(peers)}")

    def remove_selected_network(self) -> None:
        item = self.networks_tree.currentItem()
        if item is None:
            QMessageBox.information(self, "Remove Network", "Select a network first.")
            return

        network_id = item.text(1).strip()
        status = item.text(2).strip()
        if not network_id:
            return

        if status == "OK":
            reply = QMessageBox.question(
                self,
                "Remove Network",
                f"Remove {network_id}? This will disconnect it.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                self.api.leave_network(network_id)
            except Exception as e:
                QMessageBox.critical(self, "Remove Failed", str(e))
                return
        else:
            reply = QMessageBox.question(
                self,
                "Remove Network",
                f"Forget {network_id} from the UI list?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        forget_network(network_id)
        self.refresh()
        if callable(self.on_updated):
            self.on_updated()

