import logging

from .config import LOG_LEVEL


LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(threadName)s] "
    "%(name)s: %(message)s"
)
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging():
    logging.basicConfig(
        level=LOG_LEVEL.upper(),
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
