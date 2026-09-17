#!/usr/bin/env bash
# Install DigitalFrame's native dependencies on Debian/Armbian.

set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer requires a Debian/Armbian system with apt-get." >&2
  exit 1
fi

if (( EUID == 0 )); then
  apt_get=(apt-get)
elif command -v sudo >/dev/null 2>&1; then
  apt_get=(sudo apt-get)
else
  echo "Run this installer as root or install sudo." >&2
  exit 1
fi

packages=(
  # Slideshow runtime and a font for its ASS text overlays.
  fonts-dejavu-core
  mpv

  # Python and native headers used if uv must build Pillow/Pillow-HEIF.
  build-essential
  libffi-dev
  libheif-dev
  libjpeg-dev
  libwebp-dev
  pkg-config
  python3
  python3-dev
  zlib1g-dev

  # TLS/download and optional minimal-Armbian Wi-Fi helper tools.
  ca-certificates
  curl
  git
  iproute2
  iw
  systemd
  util-linux
  vim
  wpasupplicant
)

"${apt_get[@]}" update
"${apt_get[@]}" install --no-install-recommends --yes "${packages[@]}"

echo "DigitalFrame APT dependencies are installed."
mpv --version | sed -n '1p'

if command -v uv >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/uv" ]]; then
  echo "uv is already installed."
else
  if (( EUID == 0 )); then
    echo "Installing uv for root. Run this script without sudo to install uv for the DigitalFrame user." >&2
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if command -v uv >/dev/null 2>&1; then
  uv --version
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  "$HOME/.local/bin/uv" --version
else
  echo "uv was installed, but its binary is not on PATH yet. Restart the shell before continuing."
fi
