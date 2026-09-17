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
  iproute2
  iw
  systemd
  wpasupplicant
)

"${apt_get[@]}" update
"${apt_get[@]}" install --no-install-recommends --yes "${packages[@]}"

echo "DigitalFrame APT dependencies are installed."
mpv --version | sed -n '1p'
