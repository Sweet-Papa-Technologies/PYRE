from pyre.transform import (
    KEEP_HEADERS,
    stripped_header_names,
    transform_management_response,
)

VOLATILE_RESPONSE = {
    "status": 200,
    "headers": [
        {"name": "Date", "value": "Tue, 01 Jul 2026 12:00:00 GMT"},
        {"name": "Content-Type", "value": "application/json"},
        {"name": "Set-Cookie", "value": "session=abc123"},
        {"name": "X-Request-Id", "value": "f00"},
        {"name": "CF-RAY", "value": "8a1-EWR"},
        {"name": "Content-Encoding", "value": "gzip"},
    ],
    "body": b'{"n": 1}',
}


def test_strips_everything_but_allowlist():
    out = transform_management_response(VOLATILE_RESPONSE)
    names = [h["name"] for h in out["headers"]]
    assert names == ["content-encoding", "content-type"]  # lowercased + sorted


def test_body_and_status_untouched():
    out = transform_management_response(VOLATILE_RESPONSE)
    assert out["status"] == 200
    assert out["body"] == b'{"n": 1}'


def test_transform_is_idempotent():
    once = transform_management_response(VOLATILE_RESPONSE)
    twice = transform_management_response(once)
    assert once == twice


def test_replica_divergence_converges():
    """Two replicas seeing different volatile headers converge post-transform."""
    replica_b = {
        "status": 200,
        "headers": [
            {"name": "Content-Type", "value": "application/json"},
            {"name": "Date", "value": "Tue, 01 Jul 2026 12:00:01 GMT"},  # +1s
            {"name": "X-Request-Id", "value": "b4r"},  # different id
            {"name": "Content-Encoding", "value": "gzip"},
        ],
        "body": b'{"n": 1}',
    }
    assert transform_management_response(VOLATILE_RESPONSE) == transform_management_response(replica_b)


def test_stripped_header_names():
    stripped = stripped_header_names(VOLATILE_RESPONSE["headers"])
    assert stripped == ["cf-ray", "date", "set-cookie", "x-request-id"]
    assert not any(name in KEEP_HEADERS for name in stripped)
