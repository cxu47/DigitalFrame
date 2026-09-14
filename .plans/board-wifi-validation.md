# Board Wi-Fi validation — 2026-09-14

Target: `chang@192.168.1.90`, Banana Pi M2 Zero. No login or home-Wi-Fi passwords are recorded here.

## Verified capabilities

- Armbian community 26.11.0-trunk.19, Ubuntu 26.04, kernel 6.18.45-current-sunxi, ARMv7.
- NetworkManager 1.54.3 owns `wlan0`; Broadcom BCM43438, driver `brcmfmac`, firmware 7.45.98.118.
- Permanent adapter identity `ac:6a:a3:29:b9:61`; 2.4 GHz supported, 5 GHz unavailable.
- AP mode, RSN/WPA2, and CCMP advertised by both `iw` and NetworkManager. Radio is not rfkill-blocked.
- Concurrent AP/station is advertised with a shared channel restriction; implementation deliberately uses single-radio mode switching.
- System Python 3.14.4 has D-Bus and GLib. curl, dnsmasq, and iptables are installed. The standalone dnsmasq service is inactive, leaving NetworkManager to manage its DHCP instance.
- Existing custom runtime: Pygame 2.6.1 with SDL 2.32.10. HDMI is connected to card0; `.env` selects `SDL_KMSDRM_DEVICE_INDEX=0`.
- Existing board checkout started clean at `6c5686a`, before the recent recovery/preloading and newest-first commits present in the development checkout.

## Checks completed

- Helper connectivity verification returned the expected upstream interface/address.
- Initial helper installation and startup succeeded; its protected status socket reported Online on `winter` at `192.168.1.90`.
- Local automated suite passed all 256 tests after the final refinements. The offline lockfile check and source/wheel builds also passed.
- Final board suite: all 256 tests passed in the existing runtime. The HEIC test now uses a fixed fixture, so validation requires decoding rather than an unnecessary encoder.
- Commit `8305178` was committed and pushed from WSL, then pulled with a fast-forward into the board checkout. Its source checkout remained clean.
- Both services were installed and enabled for boot. HDMI initialized through KMSDRM at 1280×720, and the panel responded over the LAN with all three sections and disabled Wi-Fi submission while online. The user independently confirmed changing photos and the working panel on an iPhone.
- Startup exposed an existing stuck `serial-getty@ttyGS0` initializer holding a console lock and blocking systemd. Terminating that initializer released the lock; the frame then started without application changes. Reboot behavior still needs validation on this OS image.
- After an interruption to the development session, SSH was unreachable and the user confirmed that `DigitalFrame-8D14` was discoverable from an iPhone. This establishes live AP discovery, but does not yet establish phone authentication/DHCP/browser access.
- The first test with the updated display/panel reached a discoverable hotspot, but the user reported that the displayed password was rejected. Authentication remains unverified; the requested replacement password is stored only on the board, never in this repository.

## Installation recovery and remaining checks

The interruption occurred after the helper was running but before the updated slideshow/control panel was launched. The user ran the local terminal recovery command and confirmed the board returned to `192.168.1.90`. Complete the display/panel installation before further live outage tests, and use a bounded recovery timer for SSH testing. Subsequent deployment follows the user's requested WSL commit/push, then board pull workflow.

Remaining: confirm phone DHCP and browser access, change slideshow settings over the AP, test incorrect credentials restoring the same AP, submit working credentials, verify sync resumes and the Wi-Fi button disables, and confirm persistent overlay behavior. Update this record with actual outcomes rather than treating mocked tests as hardware proof.
