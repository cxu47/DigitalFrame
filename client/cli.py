"""Typer entry point; application imports happen only inside commands."""

import importlib
import sys

import typer


app = typer.Typer(
    help="Synchronize photos and display a digital frame slideshow.",
    add_completion=False,
    pretty_exceptions_enable=False,
)


def require_pygame() -> None:
    try:
        importlib.import_module("pygame")
    except ModuleNotFoundError as exc:
        if exc.name != "pygame":
            raise
        typer.echo(
            "Pygame is required for display commands. For a standard install, "
            "run 'uv sync --locked --no-dev'. For a board with "
            "a custom SDL build, configure its compatible Pygame source in uv. "
            "See README.md.",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def run() -> None:
    """Synchronize, display photos, and serve the Wi-Fi control panel."""
    require_pygame()
    from .main import main as run_frame

    run_frame()


@app.command()
def slideshow() -> None:
    """Display cached photos with the Wi-Fi control panel; no cloud access."""
    require_pygame()
    from .runtime import main as run_cached

    run_cached()


@app.command()
def sync() -> None:
    """Synchronize photos once without opening a display."""
    from .logging_config import configure_logging
    from .sync import sync_photos

    configure_logging()
    sync_photos()


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    # Preserve successful help output when invoked without a command.
    app(args=args or ["--help"], prog_name="digitalframe")
