import pytest

from client import logging_config


@pytest.mark.parametrize(
    "configured_level",
    ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "debug"],
)
def test_configure_logging_uses_configured_level(
    configured_level,
    monkeypatch,
):
    basic_config_calls = []
    monkeypatch.setattr(logging_config, "LOG_LEVEL", configured_level)
    monkeypatch.setattr(
        logging_config.logging,
        "basicConfig",
        lambda **kwargs: basic_config_calls.append(kwargs),
    )

    logging_config.configure_logging()

    assert basic_config_calls == [
        {
            "level": configured_level.upper(),
            "format": logging_config.LOG_FORMAT,
            "datefmt": logging_config.LOG_DATE_FORMAT,
        }
    ]
