from __future__ import annotations

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

    # Standard GNOME/Unity autostart entry.
    content = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=ZeroTier",
            "Comment=ZeroTier tray UI",
            "Exec=zerotier-gui",
            "Icon=zerotier-gui",
            "X-GNOME-Autostart-enabled=true",
        ]
    )
    AUTOSTART_FILE.write_text(content + "\n", encoding="utf-8")

