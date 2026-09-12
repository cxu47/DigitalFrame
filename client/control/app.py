"""HTML form routes; construction has no display or cloud side effects."""

from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from ..settings import INTEGER_ERROR, RuntimeSettings, parse_display_seconds
from .page import render_page


def create_app(settings: RuntimeSettings) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/")
    async def index():
        return render_page(settings.display_seconds)

    @app.post("/settings")
    async def update_settings(
        request: Request,
        display_seconds: Annotated[str | None, Form()] = None,
    ):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type and media_type not in {
            "application/x-www-form-urlencoded", "multipart/form-data",
        }:
            return render_page(settings.display_seconds, error="Submit the HTML form to change the duration.",
                               status_code=415)
        try:
            value = parse_display_seconds(display_seconds)
            settings.set_display_seconds(value)
        except ValueError:
            return render_page(settings.display_seconds, submitted=display_seconds or "",
                               error=INTEGER_ERROR, status_code=422)
        return RedirectResponse("/", status_code=303)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return render_page(settings.display_seconds, submitted="", error=INTEGER_ERROR, status_code=422)

    @app.exception_handler(HTTPException)
    async def request_error(request, exc):
        message = "Unable to read that form. Please enter the duration and try again."
        if exc.status_code == 404:
            message = "Page not found. Use the form below to change the duration."
        return render_page(settings.display_seconds, error=message, status_code=exc.status_code)

    return app
