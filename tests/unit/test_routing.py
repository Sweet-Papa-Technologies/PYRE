import json

from pyre import App, Request, Response
from pyre.application import UPGRADE


def make_request(method="GET", path="/", body=b"", query="", headers=None):
    return Request(method, path, headers=headers or {}, query_string=query, body=body)


def make_app():
    app = App()

    @app.get("/health")
    def health(req):
        return Response.json({"status": "ok"})

    @app.get("/echo/{name}")
    def echo(req):
        return Response.json({"hello": req.path_params["name"]})

    @app.get("/search")
    def search(req):
        return Response.json({"q": req.query.get("q"), "all": req.query_list.get("q")})

    @app.post("/items")
    def create(req):
        return Response.json({"created": req.json()}, status=201)

    @app.get("/boom")
    def boom(req):
        raise RuntimeError("kaput")

    return app


def body_json(response):
    return json.loads(response.body.decode())


def run_update(app, request):
    gen = app.handle_update(request)
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        return stop.value


def test_basic_route():
    response = make_app().handle_query(make_request(path="/health"))
    assert response.status == 200
    assert body_json(response) == {"status": "ok"}
    assert ("content-type", "application/json") in response.headers


def test_path_params():
    response = make_app().handle_query(make_request(path="/echo/world"))
    assert body_json(response) == {"hello": "world"}


def test_query_parsing():
    response = make_app().handle_query(make_request(path="/search", query="q=a+b&q=c%20d"))
    assert body_json(response) == {"q": "a b", "all": ["a b", "c d"]}


def test_404_upgrades_then_serves_certified():
    # non-2xx query responses must be served via update (gateway certification)
    assert make_app().handle_query(make_request(path="/nope")) is UPGRADE
    response = run_update(make_app(), make_request(path="/nope"))
    assert response.status == 404
    assert body_json(response)["error"] == "not found"


def test_405_with_allow_header():
    request = make_request(method="DELETE", path="/health")
    assert make_app().handle_query(request) is UPGRADE
    response = run_update(make_app(), make_request(method="DELETE", path="/health"))
    assert response.status == 405
    assert body_json(response)["allowed"] == ["GET"]


def test_handler_exception_becomes_500_with_message_no_traceback():
    assert make_app().handle_query(make_request(path="/boom")) is UPGRADE
    response = run_update(make_app(), make_request(path="/boom"))
    assert response.status == 500
    payload = body_json(response)
    assert payload["message"] == "kaput"
    assert "traceback" not in payload


def test_debug_mode_includes_traceback():
    app = make_app()
    app.debug = True
    payload = body_json(run_update(app, make_request(path="/boom")))
    assert "traceback" in payload


def test_post_route_upgrades_from_query_context():
    result = make_app().handle_query(
        make_request(method="POST", path="/items", body=b'{"id": "1"}')
    )
    assert result is UPGRADE


def test_post_route_runs_in_update_context():
    gen = make_app().handle_update(
        make_request(method="POST", path="/items", body=b'{"id": "1"}')
    )
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        response = stop.value
    assert response.status == 201
    assert body_json(response) == {"created": {"id": "1"}}


def test_invalid_json_becomes_400():
    gen = make_app().handle_update(make_request(method="POST", path="/items", body=b"nope"))
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        response = stop.value
    assert response.status == 400


def test_auto_promotion_rules():
    app = App()

    @app.get("/plain")
    def plain(req):
        return Response.text("x")

    @app.get("/gen")
    def gen_handler(req):
        yield  # pragma: no cover — never driven

    @app.get("/coro")
    async def coro_handler(req):
        return Response.text("x")

    @app.post("/write")
    def write(req):
        return Response.text("x")

    @app.post("/readonly", update=False)
    def readonly(req):
        return Response.text("x")

    updates = {r.path: r.update for r in app.router.routes}
    assert updates == {
        "/plain": False,
        "/gen": True,
        "/coro": True,
        "/write": True,
        "/readonly": False,
    }


def test_dict_return_coerced_to_json():
    app = App()

    @app.get("/d")
    def d(req):
        return {"a": 1}

    response = app.handle_query(make_request(path="/d"))
    assert response.status == 200
    assert body_json(response) == {"a": 1}
