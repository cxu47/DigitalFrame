#!/bin/bash
# Manual launcher for minimal Armbian. Nothing is enabled at boot.
set -eu

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
uv_bin="${UV_BIN:-$HOME/.local/bin/uv}"
frame_command="${1:-slideshow}"

if [[ "$frame_command" != "slideshow" && "$frame_command" != "run" ]]; then
  echo "Usage: $0 [slideshow|run]" >&2
  exit 2
fi

cleanup() {
  sudo /usr/bin/systemctl stop digitalframe-network.service || true
}
trap cleanup EXIT HUP INT TERM

sudo /usr/bin/systemctl start digitalframe-network.service
cd "$project_dir"
CACHE_FOLDER="${CACHE_FOLDER:-cache}" \
IDLE_SECONDS="${IDLE_SECONDS:-0.5}" \
WIFI_SETUP_ENABLED=true \
CONTROL_HOST=0.0.0.0 \
"$uv_bin" run --no-sync digitalframe "$frame_command"
