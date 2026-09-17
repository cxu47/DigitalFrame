"""Typer entry point; application imports happen only inside commands."""

import shutil
import sys

import typer


app = typer.Typer(
    help="Synchronize photos and display a digital frame slideshow.",
    add_completion=False,
    pretty_exceptions_enable=False,
)


def require_mpv() -> None:
    if shutil.which("mpv") is None:
        typer.echo(
            "The mpv executable is required for display commands. Install the OS "
            "package named 'mpv', then run 'uv sync --locked --no-dev' for the "
            "Python environment. See README.md.",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command()
def run() -> None:
    """Synchronize, display photos, and serve the Wi-Fi control panel."""
    require_mpv()
    from .main import main as run_frame

    run_frame()


@app.command()
def slideshow() -> None:
    """Display cached photos with the Wi-Fi control panel; no cloud access."""
    require_mpv()
    from .runtime import main as run_cached

    run_cached()


@app.command()
def sync() -> None:
    """Synchronize photos once without opening a display."""
    try:
        from .logging_config import configure_logging
        from .sync import sync_photos

        configure_logging()
        result = sync_photos()
    except Exception as exc:
        typer.echo(f"Sync failed: {exc}", err=True)
        raise typer.Exit(code=1) from None
    if not result.success:
        typer.echo(f"Sync failed: {result.error or 'Synchronization was cancelled.'}", err=True)
        raise typer.Exit(code=1)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    # Preserve successful help output when invoked without a command.
    app(args=args or ["--help"], prog_name="digitalframe")
