import json

from pyre import App, Response
from pyre.gateway import dispatch_query, dispatch_update, request_from_gateway


def make_app():
    app = App()

    @app.get("/health")
    def health(req):
        return Response.json({"status": "ok"})

    @app.post("/items")
    def create(req):
        return Response.json({"created": req.json()}, status=201)

    return app


def gateway_request(method="GET", url="/", headers=(), body=b""):
    return {"method": method, "url": url, "headers": list(headers), "body": body}


def run_update(app, req):
    gen = dispatch_update(app, req)
    try:
        next(gen)
        raise AssertionError("no outcalls expected")
    except StopIteration as stop:
        return stop.value


def test_request_mapping():
    req = request_from_gateway(
        gateway_request(
            method="post",
            url="/items/7?verbose=1",
            headers=[("Content-Type", "application/json")],
            body=b'{"a":1}',
        )
    )
    assert req.method == "POST"
    assert req.path == "/items/7"
    assert req.query == {"verbose": "1"}
    assert req.headers["content-type"] == "application/json"
    assert req.json() == {"a": 1}


def test_query_dispatch():
    out = dispatch_query(make_app(), gateway_request(url="/health"))
    assert out["status_code"] == 200
    assert json.loads(out["body"]) == {"status": "ok"}
    assert out["upgrade"] is None
    assert out["streaming_strategy"] is None


def test_update_route_signals_upgrade_from_query():
    out = dispatch_query(
        make_app(), gateway_request(method="POST", url="/items", body=b'{"id":1}')
    )
    assert out["upgrade"] is True


def test_update_dispatch_runs_handler():
    out = run_update(
        make_app(), gateway_request(method="POST", url="/items", body=b'{"id":1}')
    )
    assert out["status_code"] == 201
    assert json.loads(out["body"]) == {"created": {"id": 1}}


def test_404_upgrades_then_served_certified_by_update():
    # errors are re-served via update so the gateway gets a certified response
    out = dispatch_query(make_app(), gateway_request(url="/missing"))
    assert out["upgrade"] is True
    out = run_update(make_app(), gateway_request(url="/missing"))
    assert out["status_code"] == 404
    assert out["upgrade"] is None
