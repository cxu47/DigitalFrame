"""HTML form routes; construction has no display or cloud side effects."""

from typing import Annotated
import logging

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from ..settings import INTEGER_ERROR, RuntimeSettings, parse_display_seconds
from .page import render_page


logger = logging.getLogger(__name__)


def create_app(settings: RuntimeSettings, status=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def page(current, **kwargs):
        folders, selected = settings.folder_snapshot()
        if status is not None:
            status.clear("Control requests")
        return render_page(current, folders=folders, selected_folder=selected,
                           issues=status.panel_snapshot() if status is not None else (), **kwargs)

    @app.get("/")
    async def index():
        return page(settings.display_seconds)

    @app.post("/folder")
    async def update_folder(request: Request, folder: Annotated[str, Form()] = ""):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type not in {"application/x-www-form-urlencoded", "multipart/form-data"}:
            return page(settings.display_seconds, error="Submit the HTML form to change the folder.",
                        status_code=415)
        try:
            settings.set_folder(folder or None)
        except ValueError as exc:
            return page(settings.display_seconds, error=str(exc), status_code=422)
        return RedirectResponse("/", status_code=303)

    @app.post("/settings")
    async def update_settings(
        request: Request,
        display_seconds: Annotated[str | None, Form()] = None,
    ):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type and media_type not in {
            "application/x-www-form-urlencoded", "multipart/form-data",
        }:
            return page(settings.display_seconds, error="Submit the HTML form to change the duration.",
                               status_code=415)
        try:
            value = parse_display_seconds(display_seconds)
            settings.set_display_seconds(value)
        except ValueError:
            return page(settings.display_seconds, submitted=display_seconds or "",
                               error=INTEGER_ERROR, status_code=422)
        return RedirectResponse("/", status_code=303)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == "/folder":
            return page(settings.display_seconds, error="Choose an existing folder or All.", status_code=422)
        return page(settings.display_seconds, submitted="", error=INTEGER_ERROR, status_code=422)

    @app.exception_handler(HTTPException)
    async def request_error(request, exc):
        message = "Unable to read that form. Please check your selection or duration and try again."
        if exc.status_code == 404:
            message = "Page not found. Use the forms below to control the slideshow."
        return page(settings.display_seconds, error=message, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error("Control request failed; cached playback continues",
                     exc_info=(type(exc), exc, exc.__traceback__))
        if status is not None:
            status.report_exception("Control requests", exc)
        # Avoid the folder provider here: its failure may have caused this error.
        return render_page(settings.display_seconds,
                           error="The control page encountered an error. Cached playback continues; try refreshing.",
                           issues=status.panel_snapshot() if status is not None else (), status_code=500)

    return app
