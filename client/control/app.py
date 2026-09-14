"""HTML form routes; construction has no display or cloud side effects."""

from typing import Annotated
import logging
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException
from starlette.background import BackgroundTask

from ..settings import INTEGER_ERROR, RuntimeSettings, parse_display_seconds
from .page import render_page
from ..network.state import DISABLED, NetworkError, validate_credentials


logger = logging.getLogger(__name__)


def create_app(settings: RuntimeSettings, status=None, *, index=None, network=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    wifi_token = secrets.token_urlsafe(32)

    def page(current, **kwargs):
        folders, selected = settings.folder_snapshot()
        if status is not None:
            status.clear("Control requests")
        return render_page(current, folders=folders, selected_folder=selected,
                           wifi=network.snapshot() if network is not None else DISABLED, wifi_token=wifi_token,
                           folder_details=index.folder_details() if index is not None else {},
                           issues=status.panel_snapshot() if status is not None else (), **kwargs)

    @app.get("/")
    async def index_page():
        return page(settings.display_seconds)

    @app.post("/wifi")
    def update_wifi(request: Request, ssid: Annotated[str, Form()] = "",
                    password: Annotated[str, Form()] = "", token: Annotated[str, Form()] = ""):
        # No request bodies or exception representations from this route are logged.
        origin = request.headers.get("origin") or request.headers.get("referer")
        expected = urlsplit(str(request.base_url))
        provided = urlsplit(origin) if origin else None
        if not secrets.compare_digest(token, wifi_token) or (provided and (
                provided.scheme, provided.netloc) != (expected.scheme, expected.netloc)):
            return page(settings.display_seconds, error="Refresh this page before submitting Wi-Fi details.", status_code=403)
        if network is None or not network.snapshot().can_submit:
            return page(settings.display_seconds, error="Wi-Fi setup is not available now. Refresh for current status.", status_code=409)
        try:
            validate_credentials(ssid, password)
        except NetworkError as exc:
            return page(settings.display_seconds, error=str(exc), status_code=422)
        try:
            operation = network.reserve(ssid, password)
        except NetworkError as exc:
            return page(settings.display_seconds, error=str(exc), status_code=409)
        except Exception:
            return page(settings.display_seconds, error="Unable to reach the Wi-Fi helper. Please try again.", status_code=503)
        response = page(settings.display_seconds,
                        error="Trying your Wi-Fi. Your phone will disconnect from the frame. If connection fails, reconnect to the same DigitalFrame network.")
        # Only commit after the HTTP response has been sent. The helper grants
        # a short handoff delay and expires an uncommitted reservation safely.
        response.background = BackgroundTask(network.commit, operation)
        return response

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
        if request.url.path == "/wifi":
            return page(settings.display_seconds, error="Enter the SSID and password using the Wi-Fi form.", status_code=422)
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
        if request.url.path == "/wifi":
            return render_page(settings.display_seconds, error="Wi-Fi setup encountered an error. Refresh and try again.", status_code=500)
        logger.error("Control request failed; cached playback continues",
                     exc_info=(type(exc), exc, exc.__traceback__))
        if status is not None:
            status.report_exception("Control requests", exc)
        # Avoid the folder provider here: its failure may have caused this error.
        return render_page(settings.display_seconds,
                           error="The control page encountered an error. Cached playback continues; try refreshing.",
                           issues=status.panel_snapshot() if status is not None else (), status_code=500)

    return app
