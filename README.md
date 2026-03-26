# ZeroTier-GUI (Linux) - Tray-only Replica

This project provides a lightweight, production-ready Linux tray application that replicates the official ZeroTier macOS client’s menu-bar/tray behavior.

## Key features

- Tray-only UI (no main window): everything lives in the tray dropdown and sub-menus/dialogs.
- Talks to the local ZeroTier One service via `http://127.0.0.1:9993` using the `authtoken.secret` token.
- Polls joined-network status every ~4 seconds (matches the “live update” feel of the macOS client).
- Menu structure mirrors macOS wording and ordering:
  - `My Address:`
  - Joined networks list (connected networks show a checkmark)
  - Per-network details sub-menu with the four checkboxes:
    - `Allow Managed Addresses`
    - `Allow Assignment of Global IPs`
    - `Allow Default Router Override`
    - `Allow DNS Configuration`
  - `Join New Network...`
  - `Start UI at Login` toggle
  - `ZeroTier Central`
  - `About ZeroTier GUI`
  - `Quit ZeroTier UI`
- If `zerotier-one` is missing/stopped, the GUI detects it and offers to install/start it (uses `pkexec` on Debian/Ubuntu).
- Graceful error handling for missing service, connection/auth issues, and API errors.
- Dark/light theme support via Qt’s system palette.

## Screenshots (description)

The repo expects these UI moments (screenshots should be added by the project maintainer):

- Tray dropdown open: shows `My Address:` followed by joined networks.
- Clicking a network shows a sub-menu with the four macOS checkboxes, interface info, managed IP list, and `Disconnect`.
- `Join New Network...` shows a minimal dialog to paste a 16-hex-character Network ID.
- `About ZeroTier GUI` shows version, links, and licensing.

## License

MIT (see `LICENSE`).

## Build & run (developer)

1. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -U pip
   pip install -r requirements.txt
   ```

2. Run:

   ```bash
   zerotier-gui
   ```

## Debian/Ubuntu .deb packaging

### Build a .deb locally

```bash
./make_deb.sh
```

This produces a `.deb` in `./dist/`.

### One-command install (after you upload the release .deb)

Replace `YOUR_URL_HERE` with the direct link to the built `.deb`:

```bash
curl -fsSL "YOUR_URL_HERE" -o /tmp/zerotier-gui.deb && sudo apt install -y /tmp/zerotier-gui.deb
```

### Desktop integration

The package installs:

- A `.desktop` entry so the app appears as `ZeroTier` in the Applications menu.
- Icons for the desktop launcher (tray icon is generated at runtime to ensure it always matches the official orange look).

## authtoken.secret handling

The GUI tries to read:

- `/var/lib/zerotier-one/authtoken.secret`

If unreadable (permission errors), the app presents a dialog to paste the token and saves it under:

- `~/.config/zerotier-gui/authtoken.secret`

This mirrors how many Linux GUIs work around root-only tokens while keeping the UI usable.

## Extending to other distros

The code is intentionally distro-agnostic (service detection is centralized).

### Arch (PKGBUILD)

Add a PKGBUILD that:

- packages `zerotier-gui` python module
- depends on `python-pyqt6` and `python-requests`
- installs a desktop file

Example template (adjust names/versions):

```bash
pkgname="zerotier-gui"
pkgver="0.1.0"
pkgrel="1"
arch=("any")
depends=("python>=3.10" "python-requests" "python-pyqt6" "xdg-utils")

package() {
  install -Dm755 zerotier-gui "$pkgdir/usr/bin/zerotier-gui"
  cp -a zerotier_gui "$pkgdir/usr/lib/zerotier-gui/"
  install -Dm644 packaging/zerotier-gui.desktop "$pkgdir/usr/share/applications/zerotier-gui.desktop"
  install -Dm644 assets/zerotier-gui.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/zerotier-gui.svg"
}
```

### Fedora / openSUSE

Use native packaging (RPM) or Flatpak:

### Flatpak (ready in this repo)

This repository now includes complete Flatpak packaging files:

- Manifest: `flatpak/org.zerotier.ZeroTierGUI.yml`
- Desktop file: `packaging/flatpak/org.zerotier.ZeroTierGUI.desktop`
- AppStream metadata: `packaging/flatpak/org.zerotier.ZeroTierGUI.metainfo.xml`
- Build helper script: `flatpak/build-flatpak.sh`

Build locally:

```bash
sudo apt install -y flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
chmod +x flatpak/build-flatpak.sh
./flatpak/build-flatpak.sh
```

Install generated bundle:

```bash
flatpak install --user ./dist/org.zerotier.ZeroTierGUI.flatpak
flatpak run org.zerotier.ZeroTierGUI
```

Notes:

- The Flatpak build uses KDE runtime (`org.kde.Platform`) so PyQt6/Qt tray integration works reliably.
- The app uses `flatpak-spawn --host` for privileged token import fallback, so first-run token flow can still prompt via host polkit.
- ZeroTier service management remains host-side behavior.

### AppImage

Bundle Python + dependencies into an AppImage using `linuxdeploy`-style tooling.

When building non-Debian packages, keep the UI/API behavior the same and only adjust:

- the service install/start commands in `zerotier_gui/service.py`
- runtime dependencies (PyQt6 / requests / system tools)

## Project layout

- `zerotier_gui/`: application code (tray app, API client, dialogs, menu)
- `make_deb.sh`: builds the Debian package
- `install_deb.sh`: helper installer logic for packagers (optional)

