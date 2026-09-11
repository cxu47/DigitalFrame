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
            "run 'uv sync --locked --no-dev --extra display'. On a board with "
            "a custom SDL build, provision its working Pygame instead. "
            "See README.md.",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def run() -> None:
    """Synchronize in the background and display photos."""
    require_pygame()
    from .main import main as run_frame

    run_frame()


@app.command()
def slideshow() -> None:
    """Display cached photos without cloud access."""
    require_pygame()
    from .logging_config import configure_logging
    from .slideshow import show_slideshow

    configure_logging()
    show_slideshow()


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
