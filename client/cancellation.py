"""Cooperative cancellation between bounded I/O operations."""


class Cancelled(Exception):
    pass


def check_cancelled(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise Cancelled()
