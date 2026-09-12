"""Render the small form without a template-engine dependency."""

from html import escape
from importlib.resources import files
from string import Template

from fastapi.responses import HTMLResponse


def render_page(current: int, *, submitted: str | None = None,
                error: str = "", status_code: int = 200,
                folders=(), selected_folder=None) -> HTMLResponse:
    template = Template(
        files("client.control").joinpath("templates/index.html").read_text(encoding="utf-8")
    )
    return HTMLResponse(
        template.substitute(
            current=current,
            value=escape(str(current) if submitted is None else submitted, quote=True),
            error=escape(error),
            folder_options="".join(
                f'<option value="{escape(value, quote=True)}"'
                f'{" selected" if value == (selected_folder or "") else ""}>'
                f'{escape(label)}</option>'
                for value, label in [("", "All"), *((folder, folder) for folder in folders)]
            ),
        ),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )
