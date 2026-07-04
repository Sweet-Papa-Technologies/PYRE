import pytest

from pyre import App, Response
from pyre._runtime import ctx
from pyre.compat import urllib_request as urllib
from pyre.errors import OutcallFailed, OutcallInQueryContext, PyreError, ResponseTooLarge
from pyre.http_types import Request
from pyre.outcall import OutcallFuture, pump_sync


def make_response_dict(status=200, headers=(), body=b"{}"):
    return {
        "status": status,
        "headers": [{"name": n, "value": v} for n, v in headers],
        "body": body,
    }


def fake_resolver(fut):
    return fut._wrap_response(
        make_response_dict(headers=(("content-type", "application/json"),), body=b'{"ok": true}')
    )


def test_urlopen_returns_future_with_defaults():
    fut = urllib.urlopen("https://example.com/x")
    assert isinstance(fut, OutcallFuture)
    assert fut.method == "GET"
    assert fut.transform_name == "pyre_default_transform"
    assert fut.max_response_bytes == urllib.DEFAULT_MAX_RESPONSE_BYTES


def test_default_max_response_bytes_is_tight():
    # Cycle cost scales with the response allowance; the platform's implicit
    # default is 2MB (~150x more expensive). Omitting the arg must land on a
    # small cap, never the platform default.
    assert urllib.DEFAULT_MAX_RESPONSE_BYTES <= 32_768
    fut = urllib.urlopen("https://example.com/x")
    assert fut.max_response_bytes <= 32_768


def test_unsupported_method_rejected():
    with pytest.raises(PyreError):
        urllib.urlopen("https://example.com/x", method="PUT")


def test_allowlist_blocks_unlisted_host():
    from pyre.outcall import OutcallBlocked, set_allowed_hosts

    set_allowed_hosts(["api.example.com"])
    try:
        # subdomain of an allowed host is fine
        urllib.urlopen("https://api.example.com/v1/x")
        # exact host is fine
        set_allowed_hosts(["example.com"])
        urllib.urlopen("https://example.com/x")
        urllib.urlopen("https://sub.example.com/x")  # subdomain match
        # an unrelated host is refused before any call
        with pytest.raises(OutcallBlocked):
            urllib.urlopen("https://evil.test/steal")
        # look-alike suffix must NOT match (notexample.com endswith example.com
        # as a raw string, but not as a dotted subdomain)
        with pytest.raises(OutcallBlocked):
            urllib.urlopen("https://notexample.com/x")
    finally:
        set_allowed_hosts(None)


def test_no_allowlist_allows_any_host():
    from pyre.outcall import set_allowed_hosts

    set_allowed_hosts(None)
    fut = urllib.urlopen("https://anything.test/x")
    assert isinstance(fut, OutcallFuture)


def test_crlf_in_url_rejected():
    from pyre.outcall import OutcallBlocked

    with pytest.raises(OutcallBlocked):
        urllib.urlopen("https://example.com/x\r\nHost: evil")


def test_crlf_in_header_rejected():
    from pyre.outcall import OutcallBlocked

    with pytest.raises(OutcallBlocked):
        urllib.urlopen("https://example.com/x",
                       headers={"x-a": "ok\r\nX-Injected: 1"})


def test_outcall_in_query_context_raises():
    ctx.in_query = True
    try:
        with pytest.raises(OutcallInQueryContext):
            urllib.urlopen("https://example.com/x")
    finally:
        ctx.in_query = False


def test_await_style_handler_pumped():
    async def handler():
        resp = await urllib.urlopen("https://example.com/x")
        return resp.json()

    assert pump_sync(handler(), fake_resolver) == {"ok": True}


def test_generator_style_handler_pumped():
    def handler():
        resp = yield urllib.urlopen("https://example.com/x")
        return resp.status

    assert pump_sync(handler(), fake_resolver) == 200


def test_resolver_error_thrown_into_handler():
    def failing_resolver(fut):
        raise OutcallFailed("boom")

    async def handler():
        try:
            await urllib.urlopen("https://example.com/x")
            return "no-error"
        except OutcallFailed as e:
            return "caught:%s" % e

    assert pump_sync(handler(), failing_resolver) == "caught:boom"


def test_call_result_err_mapped_to_typed_errors():
    fut = urllib.urlopen("https://example.com/x")
    with pytest.raises(ResponseTooLarge):
        fut._process_call_result({"Err": "the http response body exceeds size limit of 16384"})
    with pytest.raises(OutcallFailed):
        fut._process_call_result({"Err": "SysTransient: connection reset"})


def test_call_result_ok_wrapped():
    fut = urllib.urlopen("https://example.com/x")
    resp = fut._process_call_result(
        {"Ok": make_response_dict(headers=(("Content-Type", "text/plain"),), body=b"hi")}
    )
    assert resp.status == 200
    assert resp.read() == b"hi"
    assert resp.headers["content-type"] == "text/plain"


def test_raise_for_status():
    fut = urllib.urlopen("https://example.com/x", raise_for_status=True)
    with pytest.raises(urllib.UpstreamHTTPError):
        fut._process_call_result({"Ok": make_response_dict(status=503)})


def test_end_to_end_async_route_through_app():
    app = App()

    @app.get("/quote", update=True)
    async def quote(req):
        resp = await urllib.urlopen("https://example.com/x")
        return Response.json({"upstream": resp.json()})

    request = Request("GET", "/quote")
    response = app.handle_dev(request, fake_resolver)
    assert response.status == 200
    assert b'"upstream"' in response.body
