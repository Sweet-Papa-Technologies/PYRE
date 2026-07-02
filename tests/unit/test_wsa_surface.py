"""WS-A: CORS, middleware/hooks, error handlers, validation."""

import json

import pytest

from pyre import App, Request, Response, ValidationError, validate
from pyre.application import UPGRADE


def make_request(method="GET", path="/", body=b"", query="", headers=None):
    return Request(method, path, headers=headers or {}, query_string=query, body=body)


def run_update(app, request):
    gen = app.handle_update(request)
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        return stop.value


def body_json(response):
    return json.loads(response.body.decode())


# --- validation ----------------------------------------------------------------


def test_validate_happy_path():
    schema = {"id": str, "qty": int, "note": (str, ""), "tags": [str], "meta": {"unit": str}}
    clean = validate(
        {"id": "x", "qty": 2, "tags": ["a", "b"], "meta": {"unit": "g"}, "extra": 1},
        schema,
    )
    assert clean == {"id": "x", "qty": 2, "note": "", "tags": ["a", "b"], "meta": {"unit": "g"}}


def test_validate_collects_all_errors():
    schema = {"id": str, "qty": int, "meta": {"unit": str}}
    with pytest.raises(ValidationError) as exc:
        validate({"qty": "two", "meta": {"unit": 3}}, schema)
    fields = exc.value.fields
    assert fields["id"] == "required field is missing"
    assert fields["qty"] == "expected int, got str"
    assert fields["meta.unit"] == "expected str, got int"


def test_validate_bool_is_not_int_and_int_is_float():
    with pytest.raises(ValidationError):
        validate({"n": True}, {"n": int})
    assert validate({"x": 3}, {"x": float}) == {"x": 3.0}


def test_validation_error_becomes_400_with_fields():
    app = App()

    @app.post("/items")
    def create(req):
        clean = validate(req.json(), {"id": str, "qty": int})
        return Response.json(clean, status=201)

    response = run_update(app, make_request("POST", "/items", body=b'{"id": 1}'))
    assert response.status == 400
    payload = body_json(response)
    assert payload["error"] == "validation failed"
    assert set(payload["fields"]) == {"id", "qty"}


# --- hooks -----------------------------------------------------------------------


def test_before_hook_short_circuits():
    app = App()
    calls = []

    @app.before_request
    def gate(req):
        calls.append(req.path)
        if req.headers.get("x-block"):
            return Response.json({"error": "blocked"}, status=403)

    @app.get("/open")
    def open_route(req):
        return Response.json({"ok": True})

    ok = app.handle_query(make_request(path="/open"))
    assert body_json(ok) == {"ok": True}
    blocked = app.handle_query(make_request(path="/open", headers={"x-block": "1"}))
    assert blocked is UPGRADE  # 403 is non-2xx → certified via update
    blocked = run_update(App(), make_request(path="/open"))  # sanity: fresh app 404s
    assert blocked.status == 404
    assert calls == ["/open", "/open"]


def test_after_hook_modifies_response():
    app = App()

    @app.after_request
    def stamp(req, resp):
        resp.headers.append(("x-powered-by", "pyre"))
        return resp

    @app.get("/x")
    def x(req):
        return Response.json({})

    response = app.handle_query(make_request(path="/x"))
    assert ("x-powered-by", "pyre") in response.headers


def test_after_hook_must_return_response():
    app = App()

    @app.after_request
    def broken(req, resp):
        return None

    @app.get("/x")
    def x(req):
        return Response.json({})

    assert app.handle_query(make_request(path="/x")) is UPGRADE  # 500 → upgrade
    response = run_update(app, make_request(path="/x"))
    assert response.status == 500
    assert "after_request" in body_json(response)["message"]


def test_hooks_run_in_update_path():
    app = App()
    order = []

    @app.before_request
    def before(req):
        order.append("before")

    @app.after_request
    def after(req, resp):
        order.append("after")
        return resp

    @app.post("/w")
    def w(req):
        order.append("handler")
        return Response.json({}, status=201)

    response = run_update(app, make_request("POST", "/w"))
    assert response.status == 201
    assert order == ["before", "handler", "after"]


def test_certified_snapshot_includes_after_hooks():
    app = App()

    @app.after_request
    def stamp(req, resp):
        resp.headers.append(("x-stamped", "yes"))
        return resp

    @app.get("/c", certified=True)
    def c(req):
        return Response.json({"ok": True})

    app.recertify()
    snapshot = app.certification.responses["/c"]
    assert ("x-stamped", "yes") in snapshot.headers
    served = app.handle_query(make_request(path="/c"))
    assert ("x-stamped", "yes") in served.headers
    # serving must not mutate the snapshot
    assert served is not snapshot


# --- error handlers -----------------------------------------------------------------


def test_custom_404_handler():
    app = App()

    @app.errorhandler(404)
    def not_found(req, info):
        return Response.json({"custom": True, "path": info["path"]}, status=404)

    response = run_update(app, make_request(path="/missing"))
    assert response.status == 404
    assert body_json(response) == {"custom": True, "path": "/missing"}


def test_custom_500_handler_and_broken_handler_fallback():
    app = App()

    @app.errorhandler(500)
    def boom_handler(req, info):
        return {"custom_error": info["message"]}

    @app.get("/boom")
    def boom(req):
        raise RuntimeError("kaput")

    response = run_update(app, make_request(path="/boom"))
    assert response.status == 500
    assert body_json(response) == {"custom_error": "kaput"}

    app2 = App()

    @app2.errorhandler(404)
    def broken(req, info):
        raise RuntimeError("handler broke")

    response = run_update(app2, make_request(path="/nope"))
    assert response.status == 404  # falls back to default shape
    assert body_json(response)["error"] == "not found"


# --- CORS -------------------------------------------------------------------------


def cors_app(**kwargs):
    app = App()
    app.enable_cors(**kwargs)

    @app.get("/data")
    def data(req):
        return Response.json({"n": 1})

    @app.post("/data")
    def create(req):
        return Response.json({}, status=201)

    return app


def test_cors_headers_on_response():
    app = cors_app(origins="*")
    response = app.handle_query(make_request(path="/data", headers={"origin": "https://a.example"}))
    assert ("access-control-allow-origin", "*") in response.headers


def test_cors_specific_origin_echoed_with_vary():
    app = cors_app(origins=["https://a.example"])
    response = app.handle_query(make_request(path="/data", headers={"origin": "https://a.example"}))
    assert ("access-control-allow-origin", "https://a.example") in response.headers
    assert ("vary", "origin") in response.headers
    other = app.handle_query(make_request(path="/data", headers={"origin": "https://evil.example"}))
    assert not any(h[0] == "access-control-allow-origin" for h in other.headers)


def test_cors_preflight():
    app = cors_app(origins="*")
    response = app.handle_query(
        make_request("OPTIONS", "/data", headers={"origin": "https://a.example"})
    )
    assert response.status == 204
    headers = dict(response.headers)
    assert headers["access-control-allow-origin"] == "*"
    assert "GET" in headers["access-control-allow-methods"]
    assert "POST" in headers["access-control-allow-methods"]
    assert "content-type" in headers["access-control-allow-headers"]


def test_preflight_without_cors_is_404_upgrade():
    app = App()

    @app.get("/data")
    def data(req):
        return Response.json({})

    assert app.handle_query(make_request("OPTIONS", "/data")) is UPGRADE


def test_cors_credentials_with_wildcard_rejected():
    app = App()
    with pytest.raises(ValueError):
        app.enable_cors(origins="*", allow_credentials=True)
