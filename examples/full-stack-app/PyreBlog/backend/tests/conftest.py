"""Test harness for the PyrePress app.

PYRE has no documented app-testing story (friction F1), so this replicates
the framework's own unit-test idiom (tests/unit/test_wsa_surface.py in the
PYRE repo): build a `Request`, run queries via `app.handle_query`, drive
`app.handle_update` as a generator and take the StopIteration value.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pyre.kv  # noqa: E402
from pyre import Request  # noqa: E402
from pyre.application import UPGRADE  # noqa: E402

import app as app_module  # noqa: E402

from pyrepress import config  # noqa: E402

# Routes registered at import time (the static API surface). Tests that
# publish posts add dynamic certified routes; the fixture restores this.
_BASELINE_ROUTES = list(app_module.app.router.routes)

TOKEN = config.DEFAULT_TOKEN
AUTH = {"authorization": "Bearer %s" % TOKEN}


@pytest.fixture(autouse=True)
def fresh_state():
    """Isolate every test: empty kv store, baseline routes, no certification."""
    pyre.kv.bind_backend(pyre.kv._DevBackend())
    app_module.app.router.routes = list(_BASELINE_ROUTES)
    app_module.app.certification = None
    app_module.app._certification_active = False
    yield


@pytest.fixture
def app():
    return app_module.app


# --- request helpers -------------------------------------------------------------


def make_request(method="GET", path="/", body=None, query="", headers=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    return Request(
        method, path, headers=headers or {}, query_string=query, body=body or b""
    )


def run_update(app, request):
    """Drive the update generator to completion (no outcalls in this app)."""
    gen = app.handle_update(request)
    try:
        next(gen)
        raise AssertionError("handlers in this app should not yield")
    except StopIteration as stop:
        return stop.value


def run_query(app, request):
    """Query dispatch; non-2xx and update routes return the UPGRADE sentinel."""
    return app.handle_query(request)


def body_json(response):
    return json.loads(response.body.decode())


def api(app, method, path, body=None, query="", auth=False, headers=None):
    """One-call helper: routes updates/queries the way the gateway would."""
    hdrs = dict(headers or {})
    if auth:
        hdrs.update(AUTH)
    req = make_request(method, path, body=body, query=query, headers=hdrs)
    if method == "GET":
        result = run_query(app, req)
        if result is UPGRADE:  # non-2xx: gateway re-issues as update
            return run_update(app, make_request(method, path, body=body, query=query, headers=hdrs))
        return result
    return run_update(app, req)
