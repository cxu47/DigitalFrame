"""Command-line entry point; application imports happen after argument parsing."""

import argparse
import importlib


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="digitalframe",
        description="Synchronize photos and display a digital frame slideshow.",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", help="Synchronize in the background and display photos")
    commands.add_parser("slideshow", help="Display cached photos without cloud access")
    commands.add_parser("sync", help="Synchronize photos once without opening a display")
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in {"run", "slideshow"}:
        try:
            importlib.import_module("pygame")
        except ModuleNotFoundError as exc:
            if exc.name != "pygame":
                raise
            parser.exit(
                1,
                "Pygame is required for display commands. For a standard install, "
                "run 'uv sync --locked --no-dev --extra display'. On a board with "
                "a custom SDL build, provision its working Pygame instead. "
                "See README.md.\n",
            )

    if args.command == "run":
        from .main import main as run_frame

        run_frame()
    elif args.command == "slideshow":
        from .logging_config import configure_logging
        from .slideshow import show_slideshow

        configure_logging()
        show_slideshow()
    elif args.command == "sync":
        from .logging_config import configure_logging
        from .sync import sync_photos

        configure_logging()
        sync_photos()

    return 0
