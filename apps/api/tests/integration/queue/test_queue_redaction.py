"""Operational queue diagnostics must not retain authentication credentials."""

import pytest

from genjishimada_sdk.queue_worker import safe_error

pytestmark = pytest.mark.queue


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("HTTP 401; Authorization: Bearer example-secret", "HTTP 401; Authorization: Bearer [redacted]"),
        ("authorization=bEaReR\texample-secret, retry", "authorization=bEaReR\t[redacted], retry"),
        ("Proxy-Authorization: Bearer example-secret", "Proxy-Authorization: Bearer [redacted]"),
        ("Authorization: Basic ZXhhbXBsZTpzZWNyZXQ=", "Authorization: Basic [redacted]"),
        ("Authorization=example-secret", "Authorization=[redacted]"),
        ("HTTP 401; Bearer example-secret; retry", "HTTP 401; Bearer [redacted]; retry"),
        ("token=example-secret, password: secret", "token=[redacted], password: [redacted]"),
        ("api_key=example-secret; api-key: secret", "api_key=[redacted]; api-key: [redacted]"),
        ("postgresql://worker:example-secret@database/queue", "postgresql://worker:[redacted]@database/queue"),
    ],
)
def test_queue_diagnostics_redact_credentials(diagnostic, expected):
    assert safe_error(RuntimeError(diagnostic)) == expected


def test_queue_diagnostics_preserve_useful_text_and_bound_storage():
    assert safe_error("Connection reset while polling the queue") == "Connection reset while polling the queue"
    assert len(safe_error("x" * 2000)) == 1500
