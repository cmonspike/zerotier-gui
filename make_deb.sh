#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"

mkdir -p "$DIST_DIR" "$BUILD_DIR"

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "dpkg-deb not found. Install it with: sudo apt install dpkg-deb"
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync not found. Install it with: sudo apt install rsync"
  exit 1
fi

VERSION="$(python3 -c "import re, pathlib; t=pathlib.Path('pyproject.toml').read_text(); m=re.search(r'^version\\s*=\\s*\"([^\"]+)\"', t, re.M); print(m.group(1) if m else '0.0.0')")"

PKG_NAME="zerotier-gui"
DEB_OUT="$DIST_DIR/${PKG_NAME}_${VERSION}_all.deb"

rm -rf "$BUILD_DIR/pkgroot"
PKG_ROOT="$BUILD_DIR/pkgroot"
mkdir -p "$PKG_ROOT/DEBIAN"

cat >"$PKG_ROOT/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: ZeroTier GUI contributors
Depends: python3, python3-requests, python3-pyqt6, xdg-utils
Recommends: policykit-1, gir1.2-ayatanaappindicator3-0.1
Description: Tray-only ZeroTier GUI for Linux (macOS client replica)
EOF

# Ensure the installed package directory exists.
mkdir -p "$PKG_ROOT/usr/lib/zerotier-gui"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/share/applications"
mkdir -p "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$PKG_ROOT/usr/share/doc/$PKG_NAME"

# Install python package.
mkdir -p "$PKG_ROOT/usr/lib/zerotier-gui/zerotier_gui"
rsync -a \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  "$ROOT_DIR/zerotier_gui/" "$PKG_ROOT/usr/lib/zerotier-gui/zerotier_gui/"

cat >"$PKG_ROOT/usr/bin/zerotier-gui" <<'EOF'
#!/usr/bin/env sh
set -e
export PYTHONPATH="/usr/lib/zerotier-gui:${PYTHONPATH:-}"
exec python3 -m zerotier_gui
EOF
chmod 0755 "$PKG_ROOT/usr/bin/zerotier-gui"

# Install .desktop file.
cp -a "$ROOT_DIR/packaging/zerotier-gui.desktop" "$PKG_ROOT/usr/share/applications/zerotier-gui.desktop"

# Install icon.
if [ -f "$ROOT_DIR/assets/zerotier-gui.svg" ]; then
  cp -a "$ROOT_DIR/assets/zerotier-gui.svg" "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps/zerotier-gui.svg"
fi

# Documentation.
cp -a "$ROOT_DIR/README.md" "$PKG_ROOT/usr/share/doc/$PKG_NAME/README.md"
cp -a "$ROOT_DIR/LICENSE" "$PKG_ROOT/usr/share/doc/$PKG_NAME/LICENSE"

dpkg-deb --build "$PKG_ROOT" "$DEB_OUT" >/dev/null
echo "Built: $DEB_OUT"

