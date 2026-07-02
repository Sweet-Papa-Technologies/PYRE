"""Example A — REST API with persistence (requirements §7)."""

from pyre import App, Request, Response
from pyre import kv

app = App()


@app.get("/health", certified=True)  # served with a v2 response certificate
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})


@app.get("/echo/{name}")
def echo(req: Request) -> Response:
    return Response.json({"hello": req.path_params["name"]})


@app.post("/items")  # auto-promoted to update: POST implies state writes
def create_item(req: Request) -> Response:
    body = req.json()
    kv.set("item:%s" % body["id"], body)
    return Response.json({"created": body}, status=201)


@app.get("/items/{id}")
def get_item(req: Request) -> Response:
    item = kv.get("item:%s" % req.path_params["id"])
    if item is None:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(item)
