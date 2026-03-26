from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STORE_PATH = Path.home() / ".config" / "zerotier-gui" / "known_networks.json"


def _read_store() -> dict[str, dict[str, Any]]:
    try:
        raw = STORE_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _write_store(data: dict[str, dict[str, Any]]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def remember_network(network: dict[str, Any]) -> None:
    nwid = str(network.get("id") or "").strip()
    if not nwid:
        return

    data = _read_store()
    data[nwid] = {
        "id": nwid,
        "name": str(network.get("name") or nwid),
        "allowManaged": bool(network.get("allowManaged", True)),
        "allowGlobal": bool(network.get("allowGlobal", False)),
        "allowDefault": bool(network.get("allowDefault", False)),
        "allowDNS": bool(network.get("allowDNS", False)),
    }
    _write_store(data)


def forget_network(network_id: str) -> None:
    nwid = str(network_id or "").strip()
    if not nwid:
        return
    data = _read_store()
    if nwid in data:
        del data[nwid]
        _write_store(data)


def list_known_networks() -> list[dict[str, Any]]:
    return list(_read_store().values())

