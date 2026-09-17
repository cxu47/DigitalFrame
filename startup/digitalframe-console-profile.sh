# Start DigitalFrame only for chang's physical tty1 login. SSH, serial, and
# other virtual terminals remain ordinary shells. Do not use exec here: the
# login shell must remain alive so an app exit returns to its prompt.
if [ "${USER:-}" = "chang" ] && [ -z "${SSH_CONNECTION:-}" ] && \
   [ "$(/usr/bin/tty 2>/dev/null)" = "/dev/tty1" ]; then
  /bin/bash /home/chang/DigitalFrame/startup/digitalframe-console-launcher.sh
  digitalframe_status=$?
  printf 'DigitalFrame exited with status %s; tty1 terminal is available.\n' "$digitalframe_status"
  unset digitalframe_status
fi
