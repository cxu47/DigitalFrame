# Offline Wi-Fi access point and control panel plan

Date: 2026-09-13

Status: board deployment paused (2026-09-15). Online playback/panel worked, but hotspot authentication, Wi-Fi recovery, and local console access failed during hardware testing. The user requires manual slideshow launch and no further board/startup changes. Work continues only in WSL until explicitly resumed. See `docs/board-recovery.md`.

Implementation notes: the verified board already supplies `python3-dbus` and GLib, so the privileged helper uses those OS packages without changing the frame's custom Python/Pygame environment. The initial tty1 slideshow service has been removed from the repository, and the installer no longer offers service start/enable options. This does not undo already-installed board services. The board's libheif supports decoding without encoding; the image test now uses a small fixed HEIC sample. The behavior below remains the proposed design, not a claim of successful hardware validation.

## Agreed behavior

The user clarified that the requested layout change is **HTML**, not HDMI. Organize the existing browser panel into **Slideshow control**, **Wi-Fi control**, and **Notes**. HDMI continues showing photographs and connection instructions.

When internet connectivity is lost, the board starts its own password-protected Wi-Fi network. A phone joins that network and opens the existing control panel. Cached playback, duration changes, folder selection, picture counts, and saved update dates continue working. The network transition must not restart the slideshow or reset its settings.

Offline mode stays active until the user submits an SSID and password. There are no periodic internet probes, Drive synchronization attempts, or automatic home-Wi-Fi reconnection attempts in that state. While online, detect outages through operating-system events and a bounded connectivity check. Healthy online operation keeps the Wi-Fi form visible with its submit button disabled.

**Hotspot information on the slideshow has unlimited display time.** Keep the hotspot SSID, setup password, and control-panel URL visible across every photo change until the board has successfully restored upstream connectivity. A timer, settings notification, or submitted connection attempt must not dismiss these instructions.

“Notes” means existing usage instructions, current operation messages, and relevant error history. It is not an editable notes field in this version.

## Repository findings

- `client/runtime.py` shares one `RuntimeSettings` instance between the slideshow and FastAPI. Preserve this architecture so hotspot clients control the same running slideshow.
- `client/control/templates/index.html` already uses self-contained plain HTML forms. Add one Wi-Fi form and section headings without a frontend framework or external assets.
- `client/control/server.py` supervises the listener and currently redetects an address every 15 seconds. Separate listener recovery from network/address tracking.
- `client/control/address.py` selects an address using routes and active interfaces. An AP-specific URL must instead come from the AP interface actually activated.
- `client/main.py` currently retries synchronization every `SYNC_INTERVAL`, including offline. Introduce an online gate and an event to wake the worker after recovery.
- `client/status.py` treats transport failures broadly as network issues. Wi-Fi recovery needs a separate network state, since Google authorization, certificate, and service errors do not necessarily indicate an internet outage.
- `client/overlay.py` currently says “Network connection problem. Retrying...”. Offline mode must replace that message with accurate hotspot instructions and no claim of automatic retries.
- `logs/README.md` records a Banana Pi M2 Zero running Armbian. It does not establish the board's current network manager, wireless driver capabilities, or AP reliability.

## 1. Verify the board before choosing its network backend

Perform read-only checks on the actual board, not the development computer:

```text
cat /etc/os-release
nmcli --version
systemctl is-active NetworkManager
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
iw dev
iw list
rfkill list
ip -j address show
ip -j route show table all
```

Record the Wi-Fi interface, its permanent identity, AP support, regulatory country, available bands, current owner, NetworkManager version, and current connection profiles. Inspect capabilities without printing stored passwords. Confirm required DHCP support and local firewall behavior.

Use **NetworkManager** as the first backend when it owns the board's Wi-Fi. Its API supports profiles and access-point configuration; its shared IPv4 mode supplies local addressing and DHCP/DNS. Avoid a second independent network manager competing for the same radio. [NetworkManager profile settings](https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html)

Do not assume simultaneous station/AP support. Version one deliberately switches a single radio between home-Wi-Fi mode and AP mode. If the radio cannot provide a WPA2 AP, report that prerequisite and test a compatible adapter. If NetworkManager does not manage the board, document the installed networking stack and revise the deployment portion before implementation against it; do not silently migrate a working board.

## 2. Define one network state machine

Keep immutable, thread-safe snapshots containing the state, selected interface, connected SSID, current browser URL, safe user message, and operation revision. Keep the home-Wi-Fi password out of snapshots.

| State | Network behavior | Browser Wi-Fi submit | Slideshow / Drive |
| --- | --- | --- | --- |
| Starting | Inspect current connections; make one bounded startup attempt if appropriate | Disabled, with “Checking connection” | Cache starts immediately; Drive waits |
| Online | Use working upstream connection; AP off | Disabled, with “Already connected” | Cache plays; normal scheduled Drive sync |
| Starting access point | Stop upstream attempts; activate AP and DHCP | Disabled during transition | Cache plays; Drive paused |
| Access point ready | AP remains available; no upstream probes or retries | Enabled | Cache plays; slideshow controls active; Drive paused |
| Connecting | One user-requested Wi-Fi attempt and connectivity verification | Disabled; duplicate requests rejected | Cache plays; Drive paused |
| Setup unavailable | AP unsupported, blocked radio, permissions failure, or activation failure | Disabled if Wi-Fi changes cannot work | Cache plays; explain the actual failure on HDMI and any reachable panel |

Serialize transitions. Tag every attempt with an operation ID; ignore stale completion events. Expected disconnects during station/AP switching must not initiate a second recovery operation.

### Startup and restarts

- Start cached playback and the web listener immediately; network initialization runs independently.
- If an existing upstream connection passes verification, enter Online without changing it.
- On a normal boot with a previously successful DigitalFrame Wi-Fi profile, allow one bounded activation attempt. On first setup or failure, activate the AP.
- Persist a small **non-secret** “waiting for user” flag. If a previous session entered offline setup, restarting either the app or board restores the AP and continues waiting for credentials. Restarting must not evade the user's no-retry policy.
- If power is lost during a submitted connection attempt, restore the AP at the next startup. Keep the prior successful profile until a replacement has been verified.

### Outage detection and retry policy

- Subscribe to NetworkManager device, address, and connection events. Passive event listening continues offline; it does not initiate network traffic. [Device state notifications](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.html)
- While **Online only**, run a small connectivity transaction, proposed interval 30 seconds. This detects a router losing its WAN connection while the Wi-Fi link remains associated, including in cache-only slideshow mode.
- A Drive transport failure can request the same transaction immediately. Coalesce concurrent requests into one check. Use short deadlines and a configured expected response from a connectivity endpoint, with one independent fallback endpoint. Do not equate an arbitrary redirect or captive-portal HTML page with working internet.
- A working independent connectivity check means a Google Drive failure remains a sync error. A 401/403, cloud 5xx, invalid token, or TLS certificate problem alone must not change the radio to AP mode.
- A missing usable upstream, a failed bounded connectivity transaction, or a captive portal moves to AP setup. Consider other usable upstream interfaces before disconnecting Wi-Fi; working Ethernet counts as online.
- Stop the online timer and pause Drive as soon as offline setup begins. While offline, page refreshes only read local state. Recovery requires SSID/password submission, even if the router later comes back.
- Disable automatic station activation on the dedicated interface while this controller owns it. This must cover competing profiles without deleting them. Merely setting a finite autoconnect retry count is insufficient: NetworkManager can retry after a later timeout. Record and restore any adopted profile settings on uninstall. [Autoconnect settings](https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html)
- Ensure NetworkManager's own periodic connectivity checker does not duplicate offline probes on the dedicated board. The app supplies explicit checks; NetworkManager documents `interval=0` as disabling its connectivity checker, so do not assume its on-demand check will still be usable under that configuration. Any OS configuration change belongs in the reviewed board installation. [Connectivity configuration](https://networkmanager.dev/docs/api/latest/NetworkManager.conf.html)

Proposed limits: 30 seconds between online checks, 4 seconds per probe endpoint, 45 seconds for association/DHCP, and 60 seconds for an entire submitted connection attempt. These are bounded operations, not indefinite retry loops. Validate timings on the board before finalizing defaults.

## 3. Create the access point and publish its actual URL

Provide an idempotent backend operation such as `ensure_access_point()`. Repeated calls should reuse the existing DigitalFrame AP profile rather than creating duplicate profiles or disrupting a healthy AP.

- Use a stable SSID such as `DigitalFrame-7C2A`, with a short per-device suffix.
- Generate and persist a separate random AP password once. Require WPA2/RSN with an appropriate supported cipher; do not fall back to open Wi-Fi or WEP. The home-Wi-Fi password is never displayed on HDMI.
- Prefer 2.4 GHz for initial phone compatibility if supported and permitted by the configured regulatory region. Confirm the actual board's behavior.
- Choose an IPv4 subnet from a small private pool. Prefer, for example, `10.42.0.0/24` only after checking local interface prefixes and non-default routes in all relevant routing tables, including saved home-Wi-Fi and VPN prefixes known to the board. Otherwise choose another non-overlapping subnet.
- Reuse the previous AP subnet when safe. Configure an address such as `.1` and a DHCP range excluding that address. Check activation/address-conflict results before announcing success. If all candidates conflict, explain the problem instead of silently using a colliding address.
- This avoids known board-side conflicts; it cannot prove that no unrelated network on the connecting phone overlaps. Display the actual selected address instead of promising a universal hardwired IP.
- Derive the browser URL from the activated AP interface and actual control-server port, for example `http://10.42.0.1:8000`. After connection recovery, derive it from the verified upstream interface. Clear stale addresses when an interface disappears.
- Keep Uvicorn listening on `0.0.0.0` with the existing configured port. Wi-Fi setup mode requires a wildcard listener; report an incompatible explicit bind during setup instead of presenting an unreachable AP URL.
- Only advertise “Open the control panel” once the AP address, DHCP service, and web listener are ready. Report listener failure separately from AP failure.

Use NetworkManager's shared mode for DHCP rather than implementing DHCP in Python. It also enables forwarding/NAT by default; the deployment should restrict AP forwarding if the intended network is strictly for local control, using narrowly scoped rules and preserving the existing firewall. [Shared IPv4 behavior](https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html)

There is no captive-portal redirect, DNS interception, QR code, or automatic browser popup in the first version. Users join the displayed SSID and open the displayed HTTP URL. Notes should explain that a phone may warn “No internet”; the user must remain connected to reach the frame.

## 4. Wi-Fi credential submission and rollback

Use a plain `POST /wifi` form with labeled **Wi-Fi SSID** and **Wi-Fi password** inputs and an **Apply Wi-Fi** button. Use `type="password"`; never populate it with a stored credential.

1. Check the current network state on the server. Accept requests only when setup is available; reject a stale page submitting while Online or Connecting with a clear HTML response.
2. Validate the SSID as 1–32 UTF-8 bytes, preserving intentional spaces. Preserve password bytes as entered; do not trim or include them in messages. Initially support WPA2-Personal and compatible transition networks. Apply the documented WPA-PSK input rules; pure WPA3, enterprise authentication, open networks, and captive-portal login are outside this two-field first version. [Wireless security settings](https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html)
3. Protect the mutating route with a form token and same-origin checks. Escape SSIDs and other user-controlled text. Do not expose credentials through URLs, access logs, exception messages, HTML, or process command-line arguments.
4. Accept exactly one operation and send a confirmation page before tearing down the AP: “Trying your Wi-Fi. Your phone will disconnect from the frame. If connection fails, reconnect to the same DigitalFrame network.” Queue activation after the HTTP response completes, with a short bounded handoff delay. A duplicate or refreshed submission must not start another attempt.
5. Pause/gate sync, disable the AP, and activate a temporary candidate station profile. Wait asynchronously for association and DHCP, then run the one bounded connectivity verification transaction.
6. On success, persist the new NetworkManager profile, clear the waiting flag, enter Online, and update the HDMI URL. The user reconnects their phone to home Wi-Fi and opens that address. Resume normal Drive synchronization with one immediate wake-up.
7. On incorrect credentials, missing SSID, DHCP timeout, no internet, or captive portal, discard the unsuccessful candidate, restore the same AP credentials and its subnet when still safe, and return to waiting for user input. Retain a sanitized failure message in the Wi-Fi section. Do not retry the station connection again until another submission.

On a single radio, the browser cannot remain connected during the station trial. That temporary interruption is expected; slideshow playback continues through it. Successful setup must not depend on the phone staying connected to acknowledge success. An HTTP response delivery cannot be guaranteed over a disappearing link, so the same handoff instructions also appear on HDMI.

Keep the previous successful Wi-Fi profile separate from the candidate. Store home-Wi-Fi credentials using NetworkManager's protected storage, not `.env`, the photo manifest, or a custom plaintext application log.

## 5. HTML and HDMI presentation

Use semantic section headings and native browser styling:

```text
DigitalFrame control

Slideshow control
  Current duration
  Seconds per photo [ 5 ] [Apply]
  Photo folder [All — 125 pictures — updated 2026-09-13] [Apply folder]

Wi-Fi control
  Status: Offline — connected to the frame's setup network
  Wi-Fi SSID     [                    ]
  Wi-Fi password [                    ]
  [Apply Wi-Fi]
  Latest setup result, if any

Notes
  How to connect, apply changes, and refresh this page
  Existing folder/date/order explanations
  Relevant existing error history
```

When Online, show the connected SSID or Ethernet status and keep the Wi-Fi form visible. Add the native `disabled` attribute to its submit button and make inputs read-only. A short explanation says “Already connected. Wi-Fi setup becomes available when the internet connection is lost.” Use the same disabled state during startup and connection attempts, with the appropriate explanation. Server enforcement is mandatory; browser styling alone is insufficient.

Keep the slideshow forms enabled whenever the listener is reachable, including AP mode and a pending Wi-Fi attempt. Continue lazy folder changes and image preloading unchanged. Page refresh reads the latest snapshot; no JavaScript polling or timed page reload is necessary. A page opened before an outage needs manual refresh to enable Wi-Fi setup.

Keep the existing persistent **red** network notice on HDMI, but extend it to a compact, wrapped multiline banner:

```text
Internet unavailable — cached slideshow continues.
Connect to Wi-Fi: DigitalFrame-7C2A
Setup password: <device AP password>
Open: http://10.42.0.1:8000
Enter your home Wi-Fi details to reconnect.
```

The hotspot banner has **no expiration deadline** and remains visible even when `CONTROL_URL_DISPLAY_SECONDS=0`. Repaint it on every new photo; elapsed time, photo changes, and duration/folder confirmations must not hide or replace it. Clear it only when the network state confirms successful upstream connectivity, not merely when a phone joins the hotspot, the user submits credentials, or the board associates with a router without internet access.

While connecting, retain the hotspot information and add “Trying Wi-Fi — setup hotspot temporarily unavailable” with the bounded attempt status. This makes the single-radio interruption clear without dismissing the recovery instructions. A failed attempt restores the hotspot and its ready status with no countdown. After verified success, replace the persistent banner with the normal control URL notification. Long text must wrap and remain readable on the board's HDMI resolution, rather than shrinking an entire line to illegibility. Preserve the current rule that network instructions take priority over temporary settings confirmations, while the settings still apply.

The Wi-Fi section reports its current state and the last failed user-requested connection attempt. Preserve the previous decision against filling the control panel's general history with repetitive network-error logs; existing non-network errors move under Notes.

## 6. Runtime integration and OS permissions

Run the web server and slideshow as the existing ordinary user. Put privileged interface management behind one small, root-owned helper service with a restricted local Unix socket. The helper owns the network state machine and talks to NetworkManager through its structured D-Bus API; it does not accept arbitrary shell commands. Restrict callers by socket permissions and peer identity and restrict operations to the chosen Wi-Fi interface and DigitalFrame-managed profiles.

Install helper code and its interpreter/dependencies in a root-owned location. A root service must not execute a checkout or virtual environment writable by the slideshow user. Keep the helper API limited to a safe status subscription, requesting setup, submitting one connection attempt, and reporting a possible upstream failure. Passwords travel only in the protected local request, not command arguments or status broadcasts. [NetworkManager D-Bus API](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html)

The helper persists the AP credentials and minimal recovery state, so an app crash does not remove the hotspot or leave a Wi-Fi attempt without rollback. If the helper crashes, its service restarts, reads the recovery state, and restores AP mode for interrupted setup. This is local service recovery, not periodic internet reconnection. If NetworkManager is unavailable, wait for its service/device event and surface the failure; do not spin an internet-check loop.

The app consumes network snapshots through a small client and supplies them to HTML, HDMI, and the sync gate. No Pygame work runs in the helper or network worker.

Change the sync worker to wait on an online condition rather than a timeout while offline. Cancel an in-flight sync cooperatively before switching the radio; retain stop-on-exit separately from pause-for-network. Bounded existing requests may finish, but no new Drive requests should start after the gate closes. A partially completed pass must preserve the current cache recovery/deletion safeguards. Reconnecting must wake the existing worker once, not create additional threads.

Keep listener recovery independent: a web-server crash may still have a local restart timer. It neither probes the internet nor retries Wi-Fi. Network snapshots replace the current 15-second address polling. Propagate the actual listener port, including an OS-assigned port used by tests.

Enable board Wi-Fi management only through an explicit installed-board configuration such as `WIFI_SETUP_ENABLED=true`; default it off in an ordinary development checkout. Bind the configured adapter by stable device identity. Missing helper support leaves current cached playback and any existing LAN panel available with a clear explanation.

Apply Wi-Fi control to both `digitalframe run` and `digitalframe slideshow`. The latter still performs no Drive authorization or sync; its network helper may check internet only while Online. The one-shot `digitalframe sync` command must not modify Wi-Fi or start an access point.

## 7. Planned implementation units

| File / area | Planned work |
| --- | --- |
| `client/network/state.py` | State definitions, snapshots, transition rules, operation IDs |
| `client/network/network_manager.py` | Structured NetworkManager adapter, capabilities, profiles, addresses, state events |
| `client/network/service.py` | Privileged helper, serialized transitions, online-only checks, bounded trials, AP restoration |
| `client/network/client.py` | Unprivileged status subscription and limited operation requests |
| `client/runtime.py` | Share network snapshots and retain one slideshow/settings instance |
| `client/main.py`, `client/sync.py` | Online gate, cooperative pause, immediate sync after recovery |
| `client/control/app.py`, `page.py`, `templates/index.html` | Three sections, Wi-Fi form, validation, disabled states, response-before-transition flow |
| `client/control/server.py`, `address.py` | Separate listener supervision; publish interface-specific addresses and actual port |
| `client/overlay.py`, `slideshow.py` | Readable persistent AP instructions, connecting state, recovery URL |
| `client/config.py`, `.env.example` | Opt-in board setup and bounded timing configuration; no home-Wi-Fi secrets |
| `deploy/` | Root-owned helper installation, systemd unit, socket permissions, dedicated-board network/firewall setup, removal procedure |
| `pyproject.toml`, `uv.lock` | One maintained D-Bus dependency if needed; verify the exact release on the board's Python/ARM environment |
| `tests/` | State transitions, control requests, sync gating, slideshow continuity, backend failures |
| `README.md` | Setup flow, no-retry semantics, address behavior, supported Wi-Fi types, hardware checks and deployment |

Implement in that order: backend preflight; isolated state model and fake backend; AP and connection transaction; app integration; HTML/HDMI presentation; failure tests; hardware validation and deployment instructions. No real network mutations should occur merely by importing modules or constructing test applications.

## 8. Verification and completion criteria

Automated tests use fake NetworkManager events and clocks and must never change the test machine's Wi-Fi:

- Online startup disables Wi-Fi submit; offline startup starts AP without delaying the first cached image.
- Wi-Fi link loss and internet-only outage both lead to AP mode; a Drive-only service/authentication/certificate failure does not.
- Long simulated offline time produces zero internet probes, Drive calls, and station activation attempts. Manual page refresh and slideshow settings do not cause retries.
- A single valid submission starts one bounded attempt. Duplicate, forged, stale-online, and concurrent requests are rejected without changing network state.
- Failed association, wrong password, DHCP failure, portal, timeout, helper failure, and a crash during an attempt restore or preserve AP recovery correctly.
- Successful setup clears the waiting flag, updates the actual URL, wakes sync once, and disables Wi-Fi submit on the refreshed page.
- Two clients on the AP can control the same duration/folder state. Existing newest-first ordering, preloading, folder transitions, and red overlay behavior remain intact.
- Advance the fake clock by several hours and display multiple slideshow cycles, including with `CONTROL_URL_DISPLAY_SECONDS=0`: hotspot SSID, password, and URL remain visible. Settings changes, credential submission, and failed connection attempts must not dismiss the banner. Only verified upstream recovery clears it and shows the new control URL.
- Empty cache, corrupt cache metadata, partial sync cancellation, long SSIDs, escaped HTML, invalid UTF-8/lengths, and absent AP hardware fail without stopping playback.
- AP subnet selection rejects known overlaps. URL selection ignores unrelated VPN addresses and never shows a stale station address as the AP address.
- Passwords never appear in logs, HTML, status snapshots, process arguments, or exception output. Test protected helper access and profile scoping.
- Replay service/device events and restart both helper and application to verify idempotence and the persistent waiting-for-user state.

On the actual board, connect a separate phone and verify AP discovery, DHCP, browser access, slideshow controls, wrong-password recovery, working credentials, router power-off, WAN-only unplug, airplane-mode/rejoin behavior, board reboot, and recovery from an interrupted submission. Watch physical HDMI throughout. Check a long offline period for absence of reconnect attempts and confirm the AP does not vanish when home Wi-Fi returns on its own.

Completion requires the existing automated suite plus these new tests, documented board capabilities, and a successful separate-device AP-to-station-to-AP cycle. Automated mocks alone do not establish that the Banana Pi's radio or driver can provide the hotspot.
