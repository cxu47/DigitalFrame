#!/bin/bash
# Review first, then run on the frame as:
#   sudo /bin/bash /home/chang/DigitalFrame/startup/install-startup.sh CN
#
# This stages boot configuration but deliberately does not start, stop, enable,
# disable, or restart any service. The new behavior begins at the next reboot.
set -Eeuo pipefail

readonly frame_user="chang"
readonly frame_home="/home/chang"
readonly project_dir="${frame_home}/DigitalFrame"
readonly wifi_interface="wlan0"
readonly wifi_mac="ac:6a:a3:29:b9:61"
readonly wifi_country="${1:-}"
readonly source_dir="${project_dir}/startup"
readonly getty_dropin_dir="/etc/systemd/system/getty@tty1.service.d"
readonly getty_dropin="${getty_dropin_dir}/90-digitalframe-autologin.conf"
readonly profile_hook="/etc/profile.d/digitalframe-console.sh"
readonly sudoers_rule="/etc/sudoers.d/digitalframe-network-control"

fail() {
  printf 'Refusing to install startup configuration: %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || fail "required file is missing: $1"
}

require_same_or_absent() {
  local source="$1"
  local destination="$2"
  if [[ -e "$destination" ]] && ! /usr/bin/cmp --silent "$source" "$destination"; then
    fail "existing file differs and will not be overwritten: $destination"
  fi
}

[[ "$EUID" -eq 0 ]] || fail "run this script with sudo"
[[ "$#" -eq 1 && "$wifi_country" =~ ^[A-Z]{2}$ ]] || fail "provide the target's two-letter Wi-Fi country (for example: install-startup.sh CN)"
[[ "${SUDO_USER:-}" == "$frame_user" ]] || fail "run it as: sudo /bin/bash $source_dir/install-startup.sh $wifi_country"
[[ "$(/usr/bin/id -u "$frame_user")" == "1000" ]] || fail "expected chang to have UID 1000"
[[ "$(/usr/bin/stat -c '%U' "$project_dir")" == "$frame_user" ]] || fail "$project_dir is not owned by chang"
[[ "$(/usr/bin/systemctl get-default)" == "multi-user.target" ]] || fail "the default boot target is no longer multi-user.target"
/usr/bin/systemctl is-enabled --quiet getty@tty1.service || fail "getty@tty1.service is not already enabled"

require_file "$source_dir/90-digitalframe-autologin.conf"
require_file "$source_dir/digitalframe-console-profile.sh"
require_file "$source_dir/digitalframe-network-control.sudoers"
require_file "$source_dir/digitalframe-console-launcher.sh"
require_file "$project_dir/deploy/install-network-helper.py"
require_file "$project_dir/deploy/digitalframe-network.service"
require_file "$project_dir/.env"
[[ -x "$frame_home/.local/bin/uv" ]] || fail "uv is missing at $frame_home/.local/bin/uv"
[[ -x "$project_dir/.venv/bin/digitalframe" ]] || fail "the locked DigitalFrame environment is not installed"
[[ -r "/sys/class/net/$wifi_interface/address" ]] || fail "$wifi_interface is not present"
[[ "$(<"/sys/class/net/$wifi_interface/address")" == "$wifi_mac" ]] || fail "$wifi_interface does not have the reviewed permanent MAC address"

case "$(/usr/bin/systemctl is-enabled digitalframe-network.service 2>/dev/null || true)" in
  enabled|enabled-runtime|linked|linked-runtime|alias)
    fail "digitalframe-network.service is already boot-enabled"
    ;;
esac

require_same_or_absent "$source_dir/90-digitalframe-autologin.conf" "$getty_dropin"
require_same_or_absent "$source_dir/digitalframe-console-profile.sh" "$profile_hook"
require_same_or_absent "$source_dir/digitalframe-network-control.sudoers" "$sudoers_rule"
/usr/sbin/visudo -cf "$source_dir/digitalframe-network-control.sudoers" >/dev/null

# Stage the repository's reviewed, runtime-only Wi-Fi helper. Its installer
# runs daemon-reload, but has no command that enables or starts the unit.
/usr/bin/python3 "$project_dir/deploy/install-network-helper.py" \
  --user "$frame_user" \
  --interface "$wifi_interface" \
  --mac "$wifi_mac" \
  --country "$wifi_country"

# Add only a getty override, a conditional login-profile hook, and the two
# exact passwordless service-control commands required by the launcher.
/usr/bin/mkdir -p "$getty_dropin_dir"
/usr/bin/cp "$source_dir/90-digitalframe-autologin.conf" "$getty_dropin"
/usr/bin/cp "$source_dir/digitalframe-console-profile.sh" "$profile_hook"
/usr/bin/cp "$source_dir/digitalframe-network-control.sudoers" "$sudoers_rule"
/usr/bin/chown root:root "$getty_dropin" "$profile_hook" "$sudoers_rule"
/usr/bin/chmod 0644 "$getty_dropin" "$profile_hook"
/usr/bin/chmod 0440 "$sudoers_rule"
/usr/sbin/visudo -cf "$sudoers_rule" >/dev/null
/usr/bin/systemctl daemon-reload

[[ "$(/usr/bin/systemctl get-default)" == "multi-user.target" ]] || fail "the default target changed unexpectedly"
/usr/bin/systemctl is-enabled --quiet getty@tty1.service || fail "getty@tty1.service changed unexpectedly"
[[ "$(/usr/bin/systemctl is-enabled digitalframe-network.service 2>/dev/null || true)" == "static" ]] || fail "the Wi-Fi helper is not static"
[[ "$(/usr/bin/systemctl is-active digitalframe-network.service 2>/dev/null || true)" != "active" ]] || fail "the Wi-Fi helper started unexpectedly"
/usr/bin/systemd-analyze verify getty@tty1.service digitalframe-network.service

printf '%s\n' \
  'Startup files are staged. Nothing was started, stopped, enabled, disabled, or rebooted.' \
  'On the next reboot, tty1 will autologin as chang and run DigitalFrame in the foreground.' \
  'Ctrl-C, Escape, q, or normal app exit stops the static Wi-Fi helper and leaves a tty1 shell.'
