#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/flatpak/org.zerotier.ZeroTierGUI.yml"
BUILD_DIR="$ROOT_DIR/.flatpak-builder"
REPO_DIR="$ROOT_DIR/dist/flatpak-repo"
BUNDLE="$ROOT_DIR/dist/org.zerotier.ZeroTierGUI.flatpak"

mkdir -p "$ROOT_DIR/dist"

# flatpak-builder is invoked with --user, so ensure flathub exists
# in user remotes (system remotes are not sufficient here).
if ! flatpak remotes --user --columns=name | tr -d ' ' | awk 'NR>1 {print}' | grep -qx flathub; then
  flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
fi

flatpak-builder --force-clean --user --install-deps-from=flathub "$BUILD_DIR" "$MANIFEST"
flatpak build-export "$REPO_DIR" "$BUILD_DIR"
flatpak build-bundle "$REPO_DIR" "$BUNDLE" org.zerotier.ZeroTierGUI

echo "Built bundle: $BUNDLE"
