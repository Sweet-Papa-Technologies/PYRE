"""WS-C: auth middleware + confidentiality guardrail."""

import json

import pytest

from pyre import App, Request, Response, auth, kv
from pyre._runtime import ctx


def make_request(method="GET", path="/", headers=None):
    return Request(method, path, headers=headers or {})


def run_update(app, request):
    gen = app.handle_update(request)
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        return stop.value


def protected_app(**kwargs):
    app = App()
    app.before_request(auth.require_token(valid={"tok-1"}, exempt=("/health",), **kwargs))

    @app.get("/health")
    def health(req):
        return Response.json({"status": "ok"})

    @app.get("/private")
    def private(req):
        return Response.json({"secret_stuff": 1})

    return app


def test_missing_token_gets_401():
    app = protected_app()
    response = run_update(app, make_request(path="/private"))
    assert response.status == 401
    assert ("www-authenticate", "Bearer") in response.headers


def test_valid_token_passes():
    app = protected_app()
    response = app.handle_query(
        make_request(path="/private", headers={"authorization": "bearer tok-1"})
    )
    assert response.status == 200


def test_wrong_token_and_wrong_scheme_rejected():
    app = protected_app()
    for value in ("Bearer nope", "Basic tok-1", "tok-1"):
        response = run_update(app, make_request(path="/private", headers={"authorization": value}))
        assert response.status == 401, value


def test_exempt_path_open():
    app = protected_app()
    response = app.handle_query(make_request(path="/health"))
    assert response.status == 200


def test_callable_validator_and_api_key_header():
    app = App()
    app.before_request(
        auth.require_token(valid=lambda t: t == "k-42", header="x-api-key", scheme=None)
    )

    @app.get("/p")
    def p(req):
        return Response.json({})

    ok = app.handle_query(make_request(path="/p", headers={"x-api-key": "k-42"}))
    assert ok.status == 200
    bad = run_update(app, make_request(path="/p", headers={"x-api-key": "nope"}))
    assert bad.status == 401


def test_options_exempt_for_cors_preflight():
    app = protected_app()
    app.enable_cors(origins="*")
    response = app.handle_query(
        make_request("OPTIONS", "/private", headers={"origin": "https://a.example"})
    )
    assert response.status == 204


def test_secret_guardrail_warns_on_host(capsys):
    ctx.in_query = False
    kv._warned_secret_names.clear()
    kv.set("api_key:abc", {"owner": "x"})
    kv.set("profile:1", {"name": "a", "password": "hunter2"})
    err = capsys.readouterr().err
    assert "looks like a secret" in err
    assert "api_key:abc" in err
    assert "password" in err
    # cleanup
    kv.delete("api_key:abc")
    kv.delete("profile:1")
