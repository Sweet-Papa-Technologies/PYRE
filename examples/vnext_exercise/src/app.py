"""vNext exercise app — forces Kybra to compile every new module.

Exercises pyre.tasks, pyre.assets, pyre.analytics, pyre.xnet, and the
generated Candid client so the compiler and a real replica see them.
"""

import hashlib

from pyre import App, Request, Response
from pyre import tasks, analytics, xnet
from pyre.assets import AssetStore, admin_routes

from generated.counter_service import CounterService

app = App()
app.enable_cors(origins="*")

# --- assets: a small chunked store ----------------------------------------
assets = AssetStore("media", chunk_size=45_000)


# --- tasks: durable timers, restored by the lifecycle hook ----------------
_ticks = {"count": 0}


@tasks.every(seconds=60, name="heartbeat", overlap="skip", catch_up="skip")
def heartbeat():
    _ticks["count"] += 1


@tasks.after(seconds=5, name="warmup", overlap="skip", catch_up="run_once")
def warmup():
    _ticks["count"] += 100


@app.get("/health", certified=True)
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})


@app.get("/tasks")
def list_tasks(req: Request) -> Response:
    return Response.json({"tasks": tasks.list(), "ticks": _ticks["count"]})


@app.post("/tasks/run")
def run_task(req: Request) -> Response:
    # run_now requires update context (POST routes are updates)
    name = req.json().get("name", "heartbeat")
    return Response.json({"ran": tasks.run_now(name)})


@app.get("/analytics")
def analytics_demo(req: Request) -> Response:
    table = analytics.Table.from_columns(
        {
            "city": ["a", "a", "b", "b"],
            "sales": [10, 20, 30, 40],
        }
    )
    grouped = table.group_by("city").aggregate(total=("sales", "sum"))
    return Response.json({"rows": grouped.to_records()})


@app.post("/assets/upload")
def upload_asset(req: Request) -> Response:
    body = req.body or b""
    asset_id = req.query.get("id", "demo.txt")
    digest = hashlib.sha256(body).hexdigest()
    session = assets.begin(
        asset_id, size=len(body), sha256=digest, content_type="text/plain"
    )
    # single-chunk assets only for this smoke test
    if body:
        assets.put_chunk(session["session_id"], 0, body)
    assets.finalize(session["session_id"])
    return Response.json({"asset_id": asset_id, "size": len(body)})


@app.get("/assets/{id}")
def serve_asset(req: Request) -> Response:
    try:
        return assets.response(req.path_params["id"], request=req)
    except Exception as exc:  # AssetNotFound etc.
        return Response.json({"error": str(exc)}, status=404)


@app.get("/xnet/service")
def xnet_service(req: Request) -> Response:
    # Construct a client (does not call) so xnet + candid specs compile & load.
    client = xnet.CanisterClient("aaaaa-aa", CounterService)
    return Response.json({"methods": [name for name, _ in client.service.methods]})


@app.get("/candid/echo")
def candid_echo(req: Request) -> Response:
    # Round-trips a text value through PYRE's Candid text codec AND the real
    # in-canister Rust Candid encoder/decoder. Proves the H1/H2 fix: non-ASCII
    # text must survive encode -> ic.candid_encode -> ic.candid_decode -> decode.
    from pyre import _platform as platform
    from pyre.xnet import _candid_text, _decode_candid_text
    from pyre.candid import TypeSpec

    value = req.query.get("text", "café ☃ 日本語 🚀")
    spec = TypeSpec("text")
    literal = _candid_text(spec, value)          # PYRE encoder -> Candid literal
    wire = platform.candid_encode("(%s)" % literal)  # real Rust Candid -> bytes
    text = platform.candid_decode(wire)          # real Rust Candid -> text
    decoded = _decode_candid_text(text, (spec,))[0]  # PYRE decoder
    return Response.json({"in": value, "out": decoded, "match": value == decoded})


# authenticated admin routes for the asset store
admin_routes(app, assets, token_check=lambda token: token == "smoke-secret")
