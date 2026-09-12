"""Render the small form without a template-engine dependency."""

from html import escape
from importlib.resources import files
from string import Template

from fastapi.responses import HTMLResponse


def render_page(current: int, *, submitted: str | None = None,
                error: str = "", status_code: int = 200) -> HTMLResponse:
    template = Template(
        files("client.control").joinpath("templates/index.html").read_text(encoding="utf-8")
    )
    return HTMLResponse(
        template.substitute(
            current=current,
            value=escape(str(current) if submitted is None else submitted, quote=True),
            error=escape(error),
        ),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )
