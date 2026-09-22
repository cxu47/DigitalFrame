#!/bin/bash
# Foreground launcher used only by chang's physical tty1 login.
set -u

readonly project_dir="/home/chang/DigitalFrame"
readonly uv_bin="/home/chang/.local/bin/uv"
readonly wifi_unit="digitalframe-network.service"
helper_started=false

cleanup() {
  # The narrow sudoers rule permits only this exact stop command without a
  # password. Stopping the helper restores the unchanged Netplan-owned link.
  if [[ "$helper_started" == true ]] && \
     ! /usr/bin/sudo -n /usr/bin/systemctl stop "$wifi_unit"; then
    printf 'WARNING: could not stop %s; run: sudo systemctl stop %s\n' \
      "$wifi_unit" "$wifi_unit" >&2
  fi
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$(/usr/bin/id -un)" != "chang" || "$(/usr/bin/tty 2>/dev/null)" != "/dev/tty1" ]]; then
  printf 'DigitalFrame automatic startup is restricted to chang on /dev/tty1.\n' >&2
  exit 1
fi
if [[ ! -x "$uv_bin" || ! -x "$project_dir/.venv/bin/digitalframe" ]]; then
  printf 'DigitalFrame or its locked environment is missing; leaving the terminal available.\n' >&2
  exit 1
fi
if ! /usr/bin/sudo -n /usr/bin/systemctl start "$wifi_unit"; then
  printf 'The Wi-Fi helper could not start; leaving the terminal available.\n' >&2
  exit 1
fi
helper_started=true
if ! /usr/bin/systemctl is-active --quiet "$wifi_unit"; then
  printf 'The Wi-Fi helper did not remain active; leaving the terminal available.\n' >&2
  exit 1
fi

cd "$project_dir" || exit 1

# Environment values override .env only for this process. The helper tries
# saved Wi-Fi briefly before starting its setup hotspot.
WIFI_SETUP_ENABLED=true \
CONTROL_HOST=0.0.0.0 \
"$uv_bin" run --no-sync digitalframe run
