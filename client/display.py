"""Discover a conservative HDMI mode through mpv's DRM mode listing."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import subprocess
import sys


logger = logging.getLogger(__name__)
_MODE_LINE = re.compile(
    r"\bMode\s+(?P<index>\d+):\s+(?P<name>.*?)\s+"
    r"\((?P<width>\d+)x(?P<height>\d+)@(?P<refresh>\d+(?:\.\d+)?)Hz\)"
)


@dataclass(frozen=True)
class DRMMode:
    """One mode in mpv's ordered list for the selected DRM connector."""

    index: int
    name: str
    width: int
    height: int
    refresh: float

    @property
    def interlaced(self) -> bool:
        return self.name.lower().rstrip().endswith("i")


def parse_drm_modes(output: str) -> list[DRMMode]:
    """Parse the stable human-readable mode lines emitted by drm-mode=help."""
    modes = []
    seen = set()
    for match in _MODE_LINE.finditer(output):
        mode = DRMMode(
            index=int(match.group("index")),
            name=match.group("name").strip(),
            width=int(match.group("width")),
            height=int(match.group("height")),
            refresh=float(match.group("refresh")),
        )
        identity = (mode.index, mode.width, mode.height, mode.refresh)
        if identity not in seen:
            seen.add(identity)
            modes.append(mode)
    return modes


def choose_mode(modes: list[DRMMode], *, preferred_hz: int,
                max_width: int, max_height: int) -> DRMMode | None:
    """Choose the largest progressive mode at the requested nominal rate."""
    candidates = [
        mode for mode in modes
        if not mode.interlaced
        and mode.width <= max_width
        and mode.height <= max_height
        # Covers the common 29.97/30.00 pair without treating 29 or 31 as 30.
        and abs(mode.refresh - preferred_hz) <= 0.15
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda mode: (
            mode.width * mode.height,
            mode.width,
            mode.height,
            -abs(mode.refresh - preferred_hz),
            -mode.index,
        ),
    )


def _direct_drm_available() -> bool:
    """Limit probing to Linux sessions that have no desktop display server."""
    return (
        sys.platform.startswith("linux")
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
        and Path("/dev/dri").is_dir()
    )


def preferred_drm_options(executable: str | os.PathLike[str], *,
                          preferred_hz: int, max_width: int,
                          max_height: int, timeout: float = 15) -> tuple[str, ...]:
    """Read connector modes through DRM and return mpv arguments for the best one.

    An empty tuple deliberately preserves mpv's existing automatic output and
    preferred-mode behavior whenever direct DRM is unavailable or probing fails.
    """
    if not _direct_drm_available():
        return ()
    command = [
        str(executable),
        "--no-config",
        "--vo=gpu",
        "--gpu-context=drm",
        "--force-window=immediate",
        "--audio=no",
        "--terminal=yes",
        "--drm-mode=help",
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = result.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(
            "Could not read HDMI modes through mpv; using its automatic display mode: %s",
            exc,
        )
        return ()

    modes = parse_drm_modes(output)
    selected = choose_mode(
        modes,
        preferred_hz=preferred_hz,
        max_width=max_width,
        max_height=max_height,
    )
    if selected is None:
        rates = ", ".join(
            f"{rate:g}" for rate in sorted({mode.refresh for mode in modes})
        ) or "none"
        logger.warning(
            "HDMI reported %d DRM modes but no progressive %d Hz mode at or below "
            "%dx%d (reported rates: %s); using the display's preferred mode",
            len(modes), preferred_hz, max_width, max_height, rates,
        )
        return ()

    logger.info(
        "HDMI reported %d DRM modes; selecting mode %d: %dx%d at %.2f Hz",
        len(modes), selected.index, selected.width, selected.height, selected.refresh,
    )
    # Selecting the numeric index preserves the exact EDID mode, including
    # fractional refresh rates, and uses the same DRM backend as the probe.
    return ("--vo=gpu", "--gpu-context=drm", f"--drm-mode={selected.index}")
