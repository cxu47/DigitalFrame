"""HTML form routes; construction has no display or cloud side effects."""

from typing import Annotated
import logging
import secrets
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from ..settings import (INTEGER_ERROR, RuntimeSettings, SettingsPersistenceError,
                        parse_display_seconds)
from ..update import UpdateManager
from .page import render_page
from ..network.state import DISABLED, NetworkError, validate_credentials


logger = logging.getLogger(__name__)


def create_app(settings: RuntimeSettings, status=None, *, index=None, network=None, updater=None,
               request_restart=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    wifi_token = secrets.token_urlsafe(32)
    update_token = secrets.token_urlsafe(32)
    updater = updater or UpdateManager()

    def request_language(request):
        requested = request.query_params.get("lang") if request is not None else None
        language = requested if requested in {"en", "zh"} else (
            request.cookies.get("digitalframe_language", "en")
            if request is not None else "en"
        )
        return ("zh" if language == "zh" else "en"), requested

    def page(current, *, request=None, **kwargs):
        available = settings.reconcile_selection()
        folders, selected, months, selected_months, view_mode = settings.selection_snapshot(available=available)
        if status is not None:
            status.clear("Control requests")
        language, requested = request_language(request)
        response = render_page(
            current, folders=folders, selected_folder=selected,
            months=months, selected_months=selected_months,
            view_mode=view_mode,
            wifi=network.snapshot() if network is not None else DISABLED,
            wifi_token=wifi_token, update=updater.snapshot(), update_token=update_token,
            folder_details=index.folder_details() if index is not None else {},
            month_counts=index.month_counts() if index is not None else {},
            issues=status.panel_snapshot() if status is not None else (),
            language=language, **kwargs,
        )
        if requested in {"en", "zh"}:
            response.set_cookie(
                "digitalframe_language", requested, max_age=31536000,
                httponly=True, samesite="lax",
            )
        return response

    def valid_wifi_request(request, token):
        origin = request.headers.get("origin") or request.headers.get("referer")
        expected = urlsplit(str(request.base_url))
        provided = urlsplit(origin) if origin else None
        return secrets.compare_digest(token, wifi_token) and not (provided and (
            provided.scheme, provided.netloc) != (expected.scheme, expected.netloc))

    def valid_update_request(request, token):
        origin = request.headers.get("origin") or request.headers.get("referer")
        expected = urlsplit(str(request.base_url))
        provided = urlsplit(origin) if origin else None
        return secrets.compare_digest(token, update_token) and not (provided and (
            provided.scheme, provided.netloc) != (expected.scheme, expected.netloc))

    @app.get("/")
    async def index_page(request: Request):
        return page(settings.display_seconds, request=request)

    @app.post("/update/check")
    def check_update(request: Request, update_token: Annotated[str, Form()] = ""):
        if not valid_update_request(request, update_token):
            return page(settings.display_seconds, request=request,
                        error="Refresh this page before checking for updates.", status_code=403)
        updater.check()
        return RedirectResponse("/", status_code=303)

    @app.post("/update/apply")
    def apply_update(request: Request, background_tasks: BackgroundTasks,
                     update_token: Annotated[str, Form()] = ""):
        if not valid_update_request(request, update_token):
            return page(settings.display_seconds, request=request,
                        error="Refresh this page before installing an update.", status_code=403)
        result = updater.apply()
        if result.state == "updated" and request_restart is not None:
            # Starlette runs this only after the redirect response has been
            # sent, so the browser returns to the stable home URL first.
            background_tasks.add_task(request_restart)
            return RedirectResponse("/", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.post("/wifi")
    def update_wifi(request: Request, bssid: Annotated[str, Form()] = "",
                    password: Annotated[str, Form()] = "", token: Annotated[str, Form()] = ""):
        # No request bodies or exception representations from this route are logged.
        if not valid_wifi_request(request, token):
            return page(settings.display_seconds, request=request, error="Refresh this page before submitting Wi-Fi details.", status_code=403)
        snapshot = network.snapshot() if network is not None else DISABLED
        if network is None or not snapshot.can_submit:
            return page(settings.display_seconds, request=request, error="Wi-Fi setup is not available now. Refresh for current status.", status_code=409)
        try:
            point = snapshot.access_point(bssid)
            validate_credentials(point["ssid"], password, point["bssid"])
        except NetworkError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=422)
        try:
            # Reserve and commit inside one helper request. A second socket
            # handoff proved unreliable while serving phones on the hotspot.
            network.connect(point["ssid"], point["bssid"], password)
        except NetworkError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=409)
        except Exception:
            return page(settings.display_seconds, request=request, error="Unable to reach the Wi-Fi helper. Please try again.", status_code=503)
        return RedirectResponse("/", status_code=303)

    @app.post("/wifi/refresh")
    def refresh_wifi(request: Request, token: Annotated[str, Form()] = ""):
        if not valid_wifi_request(request, token):
            return page(settings.display_seconds, request=request,
                        error="Refresh this page before requesting a Wi-Fi scan.", status_code=403)
        snapshot = network.snapshot() if network is not None else DISABLED
        if network is None or not snapshot.can_refresh:
            return page(settings.display_seconds, request=request,
                        error="Wi-Fi scanning is not available now. Reconnect and refresh the page.", status_code=409)
        try:
            network.refresh()
        except NetworkError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=409)
        except Exception:
            return page(settings.display_seconds, request=request,
                        error="Unable to reach the Wi-Fi helper. Please try again.", status_code=503)
        return RedirectResponse("/", status_code=303)

    @app.post("/folder")
    async def update_folder(request: Request, folder: Annotated[str, Form()] = ""):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type not in {"application/x-www-form-urlencoded", "multipart/form-data"}:
            return page(settings.display_seconds, request=request,
                        error="Submit the HTML form to change the folder.",
                        status_code=415)
        try:
            settings.set_folder(folder or None)
        except ValueError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=422)
        except SettingsPersistenceError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=500)
        return RedirectResponse("/", status_code=303)

    @app.post("/months")
    async def update_months(
        request: Request,
        month: Annotated[list[str] | None, Form()] = None,
    ):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type and media_type not in {
            "application/x-www-form-urlencoded", "multipart/form-data",
        }:
            return page(settings.display_seconds, request=request,
                        error="Submit the HTML form to change the photo months.",
                        status_code=415)
        try:
            settings.set_months(month or ())
        except ValueError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=422)
        except SettingsPersistenceError as exc:
            return page(settings.display_seconds, request=request, error=str(exc), status_code=500)
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
            return page(settings.display_seconds, request=request,
                        error="Submit the HTML form to change the duration.", status_code=415)
        try:
            value = parse_display_seconds(display_seconds)
            settings.set_display_seconds(value)
        except ValueError:
            return page(settings.display_seconds, request=request,
                        submitted=display_seconds or "", error=INTEGER_ERROR, status_code=422)
        except SettingsPersistenceError as exc:
            return page(settings.display_seconds, request=request, submitted=display_seconds or "",
                        error=str(exc), status_code=500)
        return RedirectResponse("/", status_code=303)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith("/wifi"):
            return page(settings.display_seconds, request=request, error="Enter the SSID and password using the Wi-Fi form.", status_code=422)
        if request.url.path == "/folder":
            return page(settings.display_seconds, request=request, error="Choose an existing folder or All.", status_code=422)
        if request.url.path == "/months":
            return page(settings.display_seconds, request=request, error="Choose one or more available months.", status_code=422)
        if request.url.path.startswith("/update"):
            return page(settings.display_seconds, request=request, error="Refresh this page before requesting an update.", status_code=422)
        return page(settings.display_seconds, request=request, submitted="", error=INTEGER_ERROR, status_code=422)

    @app.exception_handler(HTTPException)
    async def request_error(request, exc):
        message = "Unable to read that form. Please check your selection or duration and try again."
        if exc.status_code == 404:
            message = "Page not found. Use the forms below to control the slideshow."
        return page(settings.display_seconds, request=request, error=message, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        if request.url.path.startswith("/wifi"):
            return render_page(
                settings.display_seconds,
                error="Wi-Fi setup encountered an error. Refresh and try again.",
                status_code=500, language=request_language(request)[0],
            )
        logger.error("Control request failed; cached playback continues",
                     exc_info=(type(exc), exc, exc.__traceback__))
        if status is not None:
            status.report_exception("Control requests", exc)
        # Avoid the folder provider here: its failure may have caused this error.
        return render_page(settings.display_seconds,
                           error="The control page encountered an error. Cached playback continues; try refreshing.",
                           issues=status.panel_snapshot() if status is not None else (),
                           status_code=500, language=request_language(request)[0])

    return app
