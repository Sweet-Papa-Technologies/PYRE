"""pyre.static — chunked asset store, SPA serving, upload protocol, CLI."""

import base64
import gzip
import hashlib
import json

import pytest

from pyre import App, Response, kv, static
from pyre._runtime import ctx
from pyre.application import UPGRADE
from pyre.gateway import dispatch_update
from pyre.http_types import Request
from pyre.routing import Router, compile_path, is_catchall_path

TOKEN = "push-secret-1"


@pytest.fixture(autouse=True)
def clean_store():
    ctx.in_query = False
    for key in list(kv.keys()):
        kv.delete(key)
    yield
    ctx.in_query = False


def make_request(method="GET", path="/", body=b"", headers=None):
    return Request(method, path, headers=headers or {}, body=body)


def run_update(app, request):
    gen = app.handle_update(request)
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        return stop.value


def get(app, path, headers=None):
    """Query-dispatch a GET; 404s upgrade, so resolve those via update."""
    request = make_request("GET", path, headers=headers)
    response = app.handle_query(request)
    if response is UPGRADE:
        response = run_update(app, make_request("GET", path, headers=headers))
    return response


def post_json(app, path, payload, token=TOKEN):
    headers = {"authorization": "Bearer " + token} if token else {}
    request = make_request("POST", path, body=json.dumps(payload).encode(), headers=headers)
    return run_update(app, request)


def header(response, name):
    for key, value in response.headers:
        if key.lower() == name:
            return value
    return None


def body_json(response):
    return json.loads(response.body.decode())


def upload(app, path, data, gz=None, token=TOKEN, finalize=True):
    """Drive the full manifest → chunks → finalize protocol for one file."""
    entry = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if gz is not None:
        entry["gzip_size"] = len(gz)
        entry["gzip_sha256"] = hashlib.sha256(gz).hexdigest()
    resp = post_json(app, "/_pyre/static/manifest", {"assets": {path: entry}}, token=token)
    assert resp.status == 200, resp.body
    for variant, blob in (("raw", data), ("gzip", gz)):
        if blob is None:
            continue
        slices = [
            blob[i : i + static.CHUNK_RAW_SIZE]
            for i in range(0, len(blob), static.CHUNK_RAW_SIZE)
        ] or [b""]
        for index, piece in enumerate(slices):
            resp = post_json(
                app,
                "/_pyre/static/chunk",
                {
                    "path": path,
                    "variant": variant,
                    "index": index,
                    "data": base64.b64encode(piece).decode("ascii"),
                },
                token=token,
            )
            assert resp.status == 200, resp.body
    if finalize:
        resp = post_json(app, "/_pyre/static/finalize", {"paths": [path]}, token=token)
        assert resp.status == 200, resp.body
    return resp


def spa_app(**mount_kwargs):
    app = App()

    @app.get("/api/ping")
    def ping(req):
        return Response.json({"pong": True})

    static.mount(app, **mount_kwargs)
    static.admin_routes(app, TOKEN)
    return app


# --- store: chunking / reassembly --------------------------------------------


def test_store_roundtrip_small():
    meta = static.put_asset("index.html", b"<html>hi</html>")
    assert meta["chunks"] == 1
    assert meta["content_type"].startswith("text/html")
    assert static.read_asset("index.html") == b"<html>hi</html>"
    assert static.read_asset("index.html", "gzip") is None


def test_store_roundtrip_larger_than_kv_value_cap():
    data = bytes((i * 7) % 251 for i in range(100_000))  # > 64_000, 3 chunks
    meta = static.put_asset("assets/big.js", data)
    assert meta["chunks"] == 3
    assert static.read_asset("assets/big.js") == data
    # every stored kv value must fit the 64_000-byte cap
    for index in range(meta["chunks"]):
        stored = kv.get("static:assets/big.js:c:%d" % index)
        assert len(json.dumps(stored).encode()) <= kv.MAX_VALUE_SIZE


def test_store_gzip_variant_roundtrip():
    raw = b"body { color: red }" * 300
    gz = gzip.compress(raw, 9, mtime=0)
    meta = static.put_asset("assets/app.css", raw, gzip_body=gz)
    assert meta["gzip"] is True
    assert static.read_asset("assets/app.css") == raw
    assert gzip.decompress(static.read_asset("assets/app.css", "gzip")) == raw


def test_store_overwrite_trims_stale_chunks():
    static.put_asset("x.js", bytes(static.CHUNK_RAW_SIZE * 3))
    static.put_asset("x.js", b"small")
    assert static.get_meta("x.js")["chunks"] == 1
    assert kv.get("static:x.js:c:1") is None
    assert kv.get("static:x.js:c:2") is None
    assert static.read_asset("x.js") == b"small"


def test_store_list_delete_clear():
    static.put_asset("index.html", b"a")
    static.put_asset("assets/app.js", b"b")
    assert static.list_assets() == ["assets/app.js", "index.html"]
    assert static.delete_asset("assets/app.js") is True
    assert static.delete_asset("assets/app.js") is False
    assert static.clear_assets() == 1
    assert static.list_assets() == []
    assert not kv.keys()  # no orphaned chunk keys


def test_store_rejects_oversized_asset():
    with pytest.raises(ValueError):
        static.put_asset("huge.bin", bytes(static.MAX_ASSET_BYTES + 1))


# --- content types / cache headers / path normalization ----------------------


def test_content_type_mapping():
    assert static.content_type_for("index.html").startswith("text/html")
    assert static.content_type_for("assets/app-4f2a.js").startswith("text/javascript")
    assert static.content_type_for("a.css").startswith("text/css")
    assert static.content_type_for("logo.svg") == "image/svg+xml"
    assert static.content_type_for("f.woff2") == "font/woff2"
    assert static.content_type_for("m.wasm") == "application/wasm"
    assert static.content_type_for("app.js.map").startswith("application/json")
    assert static.content_type_for("blob.xyz") == static.DEFAULT_CONTENT_TYPE


def test_clean_content_type_rejects_control_chars_and_junk():
    # A well-formed client-supplied type is kept…
    assert static._clean_content_type("image/png", "a.bin") == "image/png"
    # …but CR/LF (header-injection) or other control chars fall back to the
    # extension-derived type rather than reaching a response header.
    assert static._clean_content_type("text/html\r\nX-Evil: 1", "a.js") == \
        static.content_type_for("a.js")
    assert static._clean_content_type("a/b\x00c", "a.css") == static.content_type_for("a.css")
    # Non-strings, empties, and absurd lengths also fall back.
    assert static._clean_content_type(None, "a.svg") == static.content_type_for("a.svg")
    assert static._clean_content_type("", "a.svg") == static.content_type_for("a.svg")
    assert static._clean_content_type("x/" + "y" * 300, "a.svg") == static.content_type_for("a.svg")


def test_cache_control_heuristic():
    # Vite-style hashed name -> immutable
    assert "immutable" in static.cache_control_for("assets/index-Dk7fmR6Y.js")
    assert "immutable" in static.cache_control_for("assets/app.4f2a9b1c.css")
    # html always revalidates
    assert static.cache_control_for("index.html") == "no-cache"
    # unhashed asset -> short-lived
    assert static.cache_control_for("favicon.ico") == "public, max-age=3600"
    assert static.cache_control_for("assets/logo.png") == "public, max-age=3600"


def test_normalize_path_rejects_traversal_and_ambiguity():
    assert static.normalize_path("/assets/app.js") == "assets/app.js"
    assert static.normalize_path("") == ""
    assert static.normalize_path("a/../b") is None
    assert static.normalize_path("a//b") is None
    assert static.normalize_path("./a") is None
    assert static.normalize_path("a:b") is None
    assert static.normalize_path("a\\b") is None


# --- routing: catch-all extension ---------------------------------------------


def test_catchall_compile_and_match():
    assert is_catchall_path("/{path:path}")
    assert not is_catchall_path("/items/{id}")
    regex = compile_path("/static/{path:path}")
    assert regex.match("/static/a/b/c.js").groupdict() == {"path": "a/b/c.js"}
    assert regex.match("/static/").groupdict() == {"path": ""}
    assert regex.match("/other") is None


def test_catchall_must_be_last_segment():
    with pytest.raises(ValueError):
        compile_path("/{path:path}/tail")


def test_catchall_lower_priority_regardless_of_order():
    def h(req):  # pragma: no cover - never called
        return None

    for order in ("catchall_first", "catchall_last"):
        router = Router()
        if order == "catchall_first":
            router.add("GET", "/{path:path}", h)
            api = router.add("GET", "/api/items/{id}", h)
        else:
            api = router.add("GET", "/api/items/{id}", h)
            router.add("GET", "/{path:path}", h)
        route, params, _ = router.match("GET", "/api/items/7")
        assert route is api and params == {"id": "7"}
        route, params, _ = router.match("GET", "/anything/else")
        assert route.catch_all and params == {"path": "anything/else"}


def test_catchall_cannot_be_certified():
    with pytest.raises(ValueError):
        Router().add("GET", "/{path:path}", lambda r: None, certified=True)


# --- serving ------------------------------------------------------------------


def test_serves_exact_asset_with_content_type():
    app = spa_app()
    static.put_asset("assets/app.css", b".a{}")
    response = get(app, "/assets/app.css")
    assert response.status == 200
    assert response.body == b".a{}"
    assert header(response, "content-type").startswith("text/css")


def test_root_and_index_serve_index_with_no_cache():
    app = spa_app()
    static.put_asset("index.html", b"<html>app</html>")
    for path in ("/", "/index.html"):
        response = get(app, path)
        assert response.body == b"<html>app</html>"
        assert header(response, "cache-control") == "no-cache"


def test_hashed_asset_served_immutable():
    app = spa_app()
    static.put_asset("assets/index-Dk7fmR6Y.js", b"js")
    response = get(app, "/assets/index-Dk7fmR6Y.js")
    assert "immutable" in header(response, "cache-control")


def test_spa_fallback_for_html_navigation():
    app = spa_app()
    static.put_asset("index.html", b"<html>app</html>")
    response = get(app, "/post/my-slug", headers={"accept": "text/html,*/*;q=0.8"})
    assert response.status == 200
    assert response.body == b"<html>app</html>"


def test_spa_fallback_needs_html_accept():
    app = spa_app()
    static.put_asset("index.html", b"<html>app</html>")
    response = get(app, "/post/my-slug", headers={"accept": "application/json"})
    assert response.status == 404


def test_asset_looking_path_is_real_404():
    app = spa_app()
    static.put_asset("index.html", b"<html>app</html>")
    # dot in the last segment -> a missing FILE, never SPA-fallbacked
    request = make_request("GET", "/assets/missing.js", headers={"accept": "text/html"})
    assert app.handle_query(request) is UPGRADE  # 404 -> certified via update
    response = get(app, "/assets/missing.js", headers={"accept": "text/html"})
    assert response.status == 404
    assert body_json(response)["error"] == "not found"


def test_spa_false_disables_fallback():
    app = spa_app(spa=False)
    static.put_asset("index.html", b"<html>app</html>")
    response = get(app, "/post/my-slug", headers={"accept": "text/html"})
    assert response.status == 404


def test_traversal_path_is_404():
    app = spa_app()
    static.put_asset("index.html", b"<html>app</html>")
    assert get(app, "/a/../index.html").status == 404


def test_gzip_negotiation():
    app = spa_app()
    raw = b"console.log('x');" * 400
    gz = gzip.compress(raw, 9, mtime=0)
    static.put_asset("assets/app.js", raw, gzip_body=gz)

    plain = get(app, "/assets/app.js")
    assert plain.body == raw
    assert header(plain, "content-encoding") is None
    assert header(plain, "vary") == "accept-encoding"

    zipped = get(app, "/assets/app.js", headers={"accept-encoding": "br, gzip;q=0.9"})
    assert zipped.body == gz
    assert header(zipped, "content-encoding") == "gzip"
    assert header(zipped, "vary") == "accept-encoding"

    refused = get(app, "/assets/app.js", headers={"accept-encoding": "gzip;q=0"})
    assert refused.body == raw


def test_api_routes_win_over_static_mount_any_order():
    # mount first, API second
    app = App()
    static.mount(app)

    @app.get("/api/ping")
    def ping(req):
        return Response.json({"pong": True})

    static.put_asset("index.html", b"<html>app</html>")
    assert body_json(get(app, "/api/ping", headers={"accept": "text/html"})) == {"pong": True}
    # API first, mount second (spa_app registers API before mount)
    app2 = spa_app()
    static.put_asset("index.html", b"<html>app</html>")
    assert body_json(get(app2, "/api/ping", headers={"accept": "text/html"})) == {"pong": True}


def test_placeholder_index_before_first_upload():
    app = spa_app()
    response = get(app, "/")
    assert response.status == 200
    assert b"No index.html uploaded yet" in response.body


def test_mount_under_prefix():
    app = App()
    static.mount(app, prefix="/app/")
    static.put_asset("index.html", b"<html>sub</html>")
    static.put_asset("assets/a.js", b"js")
    assert get(app, "/app").body == b"<html>sub</html>"
    assert get(app, "/app/").body == b"<html>sub</html>"
    assert get(app, "/app/assets/a.js").body == b"js"
    # outside the prefix nothing is mounted
    assert get(app, "/elsewhere").status == 404


def test_dev_dispatch_serves_assets():
    # `pyre dev` drives handle_dev: same routing/handlers, dev kv backend
    app = spa_app()
    static.put_asset("index.html", b"<html>dev</html>")
    static.put_asset("assets/a.js", b"js")

    def no_outcalls(fut):  # pragma: no cover - static serving never outcalls
        raise AssertionError("unexpected outcall")

    assert app.handle_dev(make_request("GET", "/assets/a.js"), no_outcalls).body == b"js"
    spa = app.handle_dev(
        make_request("GET", "/post/1", headers={"accept": "text/html"}), no_outcalls
    )
    assert spa.body == b"<html>dev</html>"


def test_mount_respects_existing_root_route():
    app = App()

    @app.get("/")
    def home(req):
        return Response.json({"home": True})

    static.mount(app)
    static.put_asset("index.html", b"<html>app</html>")
    assert body_json(get(app, "/")) == {"home": True}


# --- upload protocol -----------------------------------------------------------


def test_upload_roundtrip_multichunk_with_gzip():
    app = spa_app()
    data = bytes((i * 13) % 251 for i in range(static.CHUNK_RAW_SIZE * 2 + 500))
    gz = gzip.compress(data, 9, mtime=0)
    upload(app, "assets/bundle.js", data, gz=gz)
    assert static.read_asset("assets/bundle.js") == data
    assert static.read_asset("assets/bundle.js", "gzip") == gz
    served = get(app, "/assets/bundle.js", headers={"accept-encoding": "gzip"})
    assert served.body == gz
    # staging fully cleaned up
    assert not [k for k in kv.keys() if k.startswith("staticup:")]


def test_upload_requires_token():
    app = spa_app()
    payload = {"assets": {"index.html": {"size": 1, "sha256": "0" * 64}}}
    denied = post_json(app, "/_pyre/static/manifest", payload, token="wrong")
    assert denied.status == 401
    assert header(denied, "www-authenticate") is not None
    request = make_request("POST", "/_pyre/static/manifest", body=b"{}")
    assert run_update(app, request).status == 401  # no header at all


def test_manifest_rejects_bad_entries():
    app = spa_app()
    payload = {
        "assets": {
            "../evil": {"size": 1, "sha256": "0" * 64},
            "big.bin": {"size": static.MAX_ASSET_BYTES + 1, "sha256": "0" * 64},
            "nosha.js": {"size": 5},
            "ok.js": {"size": 2, "sha256": hashlib.sha256(b"ok").hexdigest()},
        }
    }
    response = post_json(app, "/_pyre/static/manifest", payload)
    assert response.status == 200
    out = body_json(response)
    assert set(out["accepted"]) == {"ok.js"}
    assert set(out["rejected"]) == {"../evil", "big.bin", "nosha.js"}
    assert out["chunk_size"] == static.CHUNK_RAW_SIZE


def test_chunk_size_and_range_enforced():
    app = spa_app()
    data = bytes(static.CHUNK_RAW_SIZE + 10)
    entry = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    post_json(app, "/_pyre/static/manifest", {"assets": {"a.bin": entry}})
    # chunk 0 must be exactly CHUNK_RAW_SIZE bytes
    short = post_json(
        app,
        "/_pyre/static/chunk",
        {"path": "a.bin", "index": 0, "data": base64.b64encode(b"tiny").decode()},
    )
    assert short.status == 400
    out_of_range = post_json(
        app,
        "/_pyre/static/chunk",
        {"path": "a.bin", "index": 2, "data": base64.b64encode(b"x").decode()},
    )
    assert out_of_range.status == 400
    no_manifest = post_json(
        app,
        "/_pyre/static/chunk",
        {"path": "other.bin", "index": 0, "data": ""},
    )
    assert no_manifest.status == 400


def test_chunk_reupload_is_idempotent():
    app = spa_app()
    data = b"hello world"
    entry = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    post_json(app, "/_pyre/static/manifest", {"assets": {"h.txt": entry}})
    chunk = {"path": "h.txt", "index": 0, "data": base64.b64encode(data).decode()}
    assert post_json(app, "/_pyre/static/chunk", chunk).status == 200
    assert post_json(app, "/_pyre/static/chunk", chunk).status == 200  # re-put: no-op
    resp = post_json(app, "/_pyre/static/finalize", {"paths": ["h.txt"]})
    assert body_json(resp)["finalized"] == ["h.txt"]
    assert static.read_asset("h.txt") == data


def test_finalize_sha_mismatch_rejected_and_old_asset_survives():
    app = spa_app()
    static.put_asset("app.js", b"OLD CONTENT")
    data = b"NEW CONTENT"
    entry = {"size": len(data), "sha256": hashlib.sha256(b"something else").hexdigest()}
    post_json(app, "/_pyre/static/manifest", {"assets": {"app.js": entry}})
    post_json(
        app,
        "/_pyre/static/chunk",
        {"path": "app.js", "index": 0, "data": base64.b64encode(data).decode()},
    )
    resp = post_json(app, "/_pyre/static/finalize", {"paths": ["app.js"]})
    assert resp.status == 400
    assert "sha256" in body_json(resp)["errors"]["app.js"]
    # live asset untouched; staging kept for a corrective re-upload
    assert static.read_asset("app.js") == b"OLD CONTENT"
    assert kv.get("staticup:app.js:meta") is not None


def test_finalize_idempotent_and_upload_replaces_content():
    app = spa_app()
    upload(app, "index.html", b"<html>v1</html>")
    resp = post_json(app, "/_pyre/static/finalize", {"paths": ["index.html"]})
    out = body_json(resp)
    assert resp.status == 200 and out["skipped"] == ["index.html"]  # re-finalize: no-op
    upload(app, "index.html", b"<html>v2</html>")
    assert get(app, "/").body == b"<html>v2</html>"


def test_list_and_delete_endpoints():
    app = spa_app()
    upload(app, "index.html", b"<html>x</html>")
    listing = app.handle_query(
        make_request("GET", "/_pyre/static/list", headers={"authorization": "Bearer " + TOKEN})
    )
    assert listing.status == 200
    assets = body_json(listing)["assets"]
    assert assets["index.html"]["sha256"] == hashlib.sha256(b"<html>x</html>").hexdigest()
    # unauthorized list is a 401 (upgraded from query)
    assert app.handle_query(make_request("GET", "/_pyre/static/list")) is UPGRADE
    deleted = post_json(app, "/_pyre/static/delete", {"paths": ["index.html"]})
    assert body_json(deleted)["deleted"] == ["index.html"]
    assert static.get_meta("index.html") is None


# --- certification ---------------------------------------------------------------


def test_certified_index_snapshot_and_recertify_after_finalize():
    app = App()
    static.mount(app, certified_index=True)
    static.admin_routes(app, TOKEN)
    app.recertify()  # canister init does this; placeholder must certify as 2xx
    assert b"No index.html" in app.certification.responses["/"].body

    def gateway_update(url, payload):
        gen = dispatch_update(
            app,
            {
                "method": "POST",
                "url": url,
                "headers": [("authorization", "Bearer " + TOKEN)],
                "body": json.dumps(payload).encode(),
            },
        )
        try:
            next(gen)
            raise AssertionError("no outcalls expected")
        except StopIteration as stop:
            return stop.value

    body = b"<html>certified!</html>"
    entry = {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    gateway_update("/_pyre/static/manifest", {"assets": {"index.html": entry}})
    gateway_update(
        "/_pyre/static/chunk",
        {"path": "index.html", "index": 0, "data": base64.b64encode(body).decode()},
    )
    out = gateway_update("/_pyre/static/finalize", {"paths": ["index.html"]})
    assert out["status_code"] == 200
    # dispatch_update recertified: the snapshot now carries the new body
    snapshot = app.certification.responses["/"]
    assert snapshot.body == body
    # queries serve the certified snapshot bytes (raw variant, no-cache)
    served = app.handle_query(make_request("GET", "/"))
    assert served.body == body
    assert header(served, "cache-control") == "no-cache"


def test_uncertified_mount_has_no_certified_routes():
    app = spa_app()  # certified_index defaults to False
    assert not app.has_certified_routes()


# --- CLI: pyre assets push --------------------------------------------------------


def make_fake_http(app):
    def fake_http(method, url, token=None, payload=None, timeout=60, connect=None):
        path = url.split("http://fake", 1)[1]
        headers = {"authorization": "Bearer " + token} if token else {}
        body = json.dumps(payload).encode() if payload is not None else b""
        request = make_request(method, path, body=body, headers=headers)
        if method == "GET":
            response = app.handle_query(request)
            if response is UPGRADE:
                response = run_update(app, make_request(method, path, body=body, headers=headers))
        else:
            response = run_update(app, request)
        try:
            parsed = json.loads(response.body.decode())
        except ValueError:
            parsed = None
        return response.status, parsed

    return fake_http


def make_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_bytes(b"<html>" + b"pyre " * 200 + b"</html>")
    (dist / "assets" / "app-4f2a9b1c.js").write_bytes(b"console.log('hi');" * 300)
    (dist / "assets" / "logo.png").write_bytes(b"\x89PNG13379")
    return dist


def push_args(dist, **overrides):
    import types

    defaults = dict(
        dist=str(dist), url="http://fake", token=TOKEN,
        admin_prefix="/_pyre/static", no_gzip=False, connect=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_cli_assets_push_end_to_end(monkeypatch, tmp_path, capsys):
    from pyre import cli

    app = spa_app()
    monkeypatch.setattr(cli, "_http_json", make_fake_http(app))
    dist = make_dist(tmp_path)

    assert cli.cmd_assets_push(push_args(dist)) == 0
    # everything serves, with the right negotiation
    index = get(app, "/")
    assert index.body.startswith(b"<html>")
    js = get(app, "/assets/app-4f2a9b1c.js", headers={"accept-encoding": "gzip"})
    assert header(js, "content-encoding") == "gzip"
    assert gzip.decompress(js.body) == b"console.log('hi');" * 300
    assert "immutable" in header(js, "cache-control")
    png = get(app, "/assets/logo.png")
    assert png.body == b"\x89PNG13379"
    assert header(png, "vary") is None  # binary: no gzip variant stored

    # a second push skips everything (sha match)
    capsys.readouterr()
    assert cli.cmd_assets_push(push_args(dist)) == 0
    assert "up to date" in capsys.readouterr().out


def test_cli_assets_push_bad_token(monkeypatch, tmp_path):
    from pyre import cli

    app = spa_app()
    monkeypatch.setattr(cli, "_http_json", make_fake_http(app))
    assert cli.cmd_assets_push(push_args(make_dist(tmp_path), token="nope")) == 1


def test_mount_update_flag_routes_assets_through_update():
    # update=True marks the catch-all (and uncertified index) as update
    # routes so a canister-hosted SPA works behind the certifying gateway.
    from pyre.application import App
    from pyre import static as st

    app = App()
    st.mount(app, update=True)
    asset = app.router.match("GET", "/assets/app-abc1234.js")[0]
    index = app.router.match("GET", "/")[0]
    assert asset.update is True
    assert index.update is True

    plain = App()
    st.mount(plain, update=False)
    assert plain.router.match("GET", "/assets/app-abc1234.js")[0].update is False


def test_mount_certified_index_stays_query_even_with_update():
    from pyre.application import App
    from pyre import static as st

    app = App()
    st.mount(app, update=True, certified_index=True)
    # a certified index serves from its snapshot (fast query), not update
    index = app.router.match("GET", "/")[0]
    assert index.update is False
    assert index.certified is True
    # assets still ride update
    assert app.router.match("GET", "/assets/x-12345678.js")[0].update is True
