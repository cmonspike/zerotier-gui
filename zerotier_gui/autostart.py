from __future__ import annotations

import os
from pathlib import Path


AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "zerotier-gui.desktop"


def is_autostart_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def set_autostart_enabled(enabled: bool) -> None:
    AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not enabled:
        try:
            AUTOSTART_FILE.unlink()
        except FileNotFoundError:
            pass
        return

    # Standard desktop autostart entry.
    flatpak_id = os.environ.get("FLATPAK_ID", "").strip()
    if flatpak_id:
        exec_cmd = f"flatpak run {flatpak_id}"
        icon_name = flatpak_id
    else:
        exec_cmd = "zerotier-gui"
        icon_name = "zerotier-gui"

    content = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=ZeroTier-Gui",
            "Comment=ZeroTier tray UI",
            f"Exec={exec_cmd}",
            f"Icon={icon_name}",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
        ]
    )
    AUTOSTART_FILE.write_text(content + "\n", encoding="utf-8")

