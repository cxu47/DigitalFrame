"""Render the small form without a template-engine dependency."""

from html import escape
from importlib.resources import files
from string import Template

from fastapi.responses import HTMLResponse
from ..network.state import DISABLED


def _folder_label(name, details):
    if details is None:
        return name
    date = details.updated.date().isoformat() if details.updated is not None else "unknown"
    noun = "picture" if details.count == 1 else "pictures"
    return f"{name} — {details.count} {noun} — updated {date}"


def render_page(current: int, *, submitted: str | None = None,
                error: str = "", status_code: int = 200,
                folders=(), selected_folder=None, issues=(), folder_details=None,
                wifi=DISABLED, wifi_token="") -> HTMLResponse:
    folder_details = folder_details or {}
    template = Template(
        files("client.control").joinpath("templates/index.html").read_text(encoding="utf-8")
    )
    return HTMLResponse(
        template.substitute(
            current=current,
            value=escape(str(current) if submitted is None else submitted, quote=True),
            error=escape(error),
            wifi_status=escape(wifi.message),
            wifi_ssid=escape(wifi.ssid, quote=True),
            wifi_token=escape(wifi_token, quote=True),
            wifi_disabled="" if wifi.can_submit else " disabled",
            wifi_readonly="" if wifi.can_submit else " readonly",
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
