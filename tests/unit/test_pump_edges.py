"""WS-E: coroutine-pump edge cases — where hand-rolled async breaks."""

import pytest

from pyre import App, Request, Response
from pyre.compat import urllib_request as urllib
from pyre.errors import OutcallFailed, PyreError
from pyre.outcall import pump_sync


def make_response(n):
    def resolver(fut):
        return fut._wrap_response(
            {
                "status": 200,
                "headers": [{"name": "content-type", "value": "application/json"}],
                "body": ('{"n": %d}' % n).encode(),
            }
        )

    return resolver


def counting_resolver():
    state = {"count": 0}

    def resolver(fut):
        state["count"] += 1
        return make_response(state["count"])(fut)

    return resolver, state


def test_multi_await_handler():
    resolver, state = counting_resolver()

    async def handler():
        first = await urllib.urlopen("https://a.example/1")
        second = await urllib.urlopen("https://a.example/2")
        third = await urllib.urlopen("https://a.example/3")
        return [first.json()["n"], second.json()["n"], third.json()["n"]]

    assert pump_sync(handler(), resolver) == [1, 2, 3]
    assert state["count"] == 3


def test_multi_yield_generator_handler():
    resolver, state = counting_resolver()

    def handler():
        first = yield urllib.urlopen("https://a.example/1")
        second = yield urllib.urlopen("https://a.example/2")
        return first.json()["n"] + second.json()["n"]

    assert pump_sync(handler(), resolver) == 3
    assert state["count"] == 2


def test_exception_through_await_recovers_and_continues():
    calls = {"n": 0}

    def flaky_resolver(fut):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OutcallFailed("first call failed")
        return make_response(42)(fut)

    async def handler():
        try:
            await urllib.urlopen("https://a.example/fails")
        except OutcallFailed:
            resp = await urllib.urlopen("https://a.example/retry")
            return {"recovered": resp.json()["n"]}

    assert pump_sync(handler(), flaky_resolver) == {"recovered": 42}


def test_exception_through_await_propagates_to_500():
    app = App()

    @app.get("/q", update=True)
    async def q(req):
        await urllib.urlopen("https://a.example/x")
        return Response.json({})

    def failing(fut):
        raise OutcallFailed("nope")

    response = app.handle_dev(Request("GET", "/q"), failing)
    assert response.status == 500
    assert b"nope" in response.body


def test_awaiting_a_non_outcall_is_a_clear_error():
    class NotAFuture:
        def __await__(self):
            yield self
            return None

    async def handler():
        return await NotAFuture()

    with pytest.raises(PyreError, match="only OutcallFutures"):
        pump_sync(handler(), make_response(1))


def test_handler_raising_before_any_await():
    async def handler():
        raise RuntimeError("early")

    with pytest.raises(RuntimeError, match="early"):
        pump_sync(handler(), make_response(1))
