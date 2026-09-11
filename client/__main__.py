"""Allow the CLI to run as ``python -m client``."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
