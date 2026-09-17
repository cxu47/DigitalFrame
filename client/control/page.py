"""Render the small form without a template-engine dependency."""

from html import escape
from importlib.resources import files
from string import Template

from fastapi.responses import HTMLResponse
from ..network.state import DISABLED


_TEMPLATE = Template(
    files("client.control").joinpath("templates/index.html").read_text(encoding="utf-8")
)


def _folder_label(name, details):
    if details is None:
        return name
    date = details.updated.date().isoformat() if details.updated is not None else "unknown"
    noun = "picture" if details.count == 1 else "pictures"
    return f"{name} — {details.count} {noun} — updated {date}"


def render_page(current: int, *, submitted: str | None = None,
                error: str = "", status_code: int = 200,
                folders=(), selected_folder=None, issues=(), folder_details=None,
                wifi=DISABLED, wifi_token="", update=None, update_token="") -> HTMLResponse:
    folder_details = folder_details or {}
    return HTMLResponse(
        _TEMPLATE.substitute(
            current=current,
            value=escape(str(current) if submitted is None else submitted, quote=True),
            error=escape(error),
            wifi_status=escape(wifi.message),
            wifi_current=(f'<p>Current Wi-Fi: {escape(wifi.ssid)}</p>' if wifi.ssid else ""),
            wifi_options="".join(
                f'<option value="{escape(point["bssid"], quote=True)}"'
                f'{"" if point.get("supported") and wifi.state == "ap" else " disabled"}>'
                f'{escape(point["ssid"])} — {escape(point["bssid"])} — '
                f'ch {point.get("channel") or "?"} — {point.get("signal", "?")} dBm — '
                f'{escape(point.get("security", "Unknown"))}</option>'
                for point in wifi.access_points
            ) or '<option value="" disabled selected>No access points found; use Refresh access points below</option>',
            wifi_token=escape(wifi_token, quote=True),
            wifi_disabled="" if wifi.can_submit else " disabled",
            wifi_refresh_disabled="" if wifi.can_refresh else " disabled",
            wifi_readonly="" if wifi.can_submit else " readonly",
            update_status=escape(update.message if update is not None else "Updates have not been checked."),
            update_token=escape(update_token, quote=True),
            update_form=(
                '<form method="post" action="/update/apply">'
                f'<input type="hidden" name="update_token" value="{escape(update_token, quote=True)}">'
                '<button type="submit">Install update</button></form>'
                if update is not None and update.can_apply else ""
            ),
            issues="".join(
                '<p style="color: red">'
                f'{escape(item["time"])} — {escape(item["source"])} '
                f'({"active" if item["active"] else "recovered"}): {escape(item["message"])}</p>'
                for item in issues
            ),
            folder_options="".join(
                f'<option value="{escape(value, quote=True)}"'
                f'{" selected" if value == (selected_folder or "") else ""}>'
                f'{escape(_folder_label(label, folder_details.get(value or None)))}</option>'
                for value, label in [("", "All"), *((folder, folder) for folder in folders)]
            ),
        ),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )
