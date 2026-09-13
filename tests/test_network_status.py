"""Keep network failures on the frame, separate from other control-page errors."""

import errno
import socket
import ssl

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError, ReadTimeout
from google.auth.exceptions import TransportError
from httplib2 import ServerNotFoundError

from client.status import RuntimeStatus, is_network_error


@pytest.mark.parametrize('error,expected', [
    (ssl.SSLError('SSL disconnected'), True),
    (socket.gaierror('DNS unavailable'), True),
    (ConnectionError('Disconnected'), True),
    (TimeoutError('Timed out'), True),
    (RequestsConnectionError('Connection failed'), True),
    (ReadTimeout('Read timed out'), True),
    (TransportError('Authorization transport failed'), True),
    (ServerNotFoundError('DNS failed'), True),
    (OSError(errno.ENETUNREACH, 'No route'), True),
    (OSError(errno.EADDRINUSE, 'Port occupied'), False),
    (OSError(errno.ENOSPC, 'Disk full'), False),
    (ValueError('Checksum mismatch'), False),
])
def test_network_classification_does_not_hide_unrelated_failures(error, expected):
    assert is_network_error(error) is expected


def test_wrapped_failure_is_detected_and_all_network_sources_must_recover():
    wrapped = RuntimeError('Could not start listener')
    wrapped.__cause__ = OSError(errno.EADDRNOTAVAIL, 'Network interface unavailable')
    assert is_network_error(wrapped)
    status = RuntimeStatus()
    status.report_exception('Sync', ssl.SSLError('Disconnected'))
    status.report('Network address', 'No network address', network=True)
    status.report('Photos', 'Unreadable photo')
    assert status.network_problem()
    assert [entry['source'] for entry in status.panel_snapshot()] == ['Photos']
    status.clear('Sync')
    assert status.network_problem()
    status.clear('Network address')
    assert not status.network_problem()
    assert [entry['source'] for entry in status.panel_snapshot()] == ['Photos']


def test_control_page_omits_active_and_recovered_network_errors():
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings
    status = RuntimeStatus()
    status.report_exception('Sync', ssl.SSLError('Wi-Fi disconnected'))
    status.report('Network address', 'No network address', network=True)
    status.report('Photos', 'Unreadable photo')
    with TestClient(create_app(RuntimeSettings(5), status)) as browser:
        for recovered in [False, True]:
            if recovered:
                status.clear('Sync')
                status.clear('Network address')
            response = browser.get('/')
            assert response.status_code == 200
            assert 'Wi-Fi disconnected' not in response.text
            assert 'No network address' not in response.text
            assert 'Unreadable photo' in response.text
