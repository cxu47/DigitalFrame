import logging

from client import main


def test_main_runs_initial_sync_and_slideshow(
    monkeypatch,
    caplog,
):
    calls = []
    thread_arguments = {}

    class FakeThread:
        def __init__(self, **kwargs):
            thread_arguments.update(kwargs)

        def start(self):
            calls.append("thread")

    monkeypatch.setattr(
        main,
        "configure_logging",
        lambda: calls.append("configure"),
    )
    monkeypatch.setattr(main, "sync_photos", lambda: calls.append("sync"))
    monkeypatch.setattr(
        main,
        "show_slideshow",
        lambda: calls.append("slideshow"),
    )
    monkeypatch.setattr(main.threading, "Thread", FakeThread)

    with caplog.at_level(logging.INFO, logger=main.__name__):
        main.main()

    assert calls == ["configure", "sync", "thread", "slideshow"]
    assert thread_arguments == {
        "target": main.sync_loop,
        "daemon": True,
        "name": "photo-sync",
    }
    assert caplog.messages == [
        "DigitalFrame client starting",
        "Background sync thread started",
        "DigitalFrame client stopped",
    ]


def test_sync_loop_logs_interval_before_sleep(monkeypatch, caplog):
    def stop_loop(interval):
        raise RuntimeError("stop test loop")

    monkeypatch.setattr(main.time, "sleep", stop_loop)

    with caplog.at_level(logging.INFO, logger=main.__name__):
        try:
            main.sync_loop()
        except RuntimeError as exc:
            assert str(exc) == "stop test loop"

    assert caplog.messages == [
        f"Background sync loop started with a {main.SYNC_INTERVAL}-second interval"
    ]
