"""A minimal PYRE app: two GETs and a POST. Grow it from here."""

from pyre import App, Request, Response
from pyre import kv

app = App()


@app.get("/health", certified=True)  # served with a v2 response certificate
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})


@app.get("/echo/{name}")
def echo(req: Request) -> Response:
    return Response.json({"hello": req.path_params["name"]})


@app.post("/items")  # POST routes run as updates: writes persist
def create_item(req: Request) -> Response:
    body = req.json()
    kv.set("item:%s" % body["id"], body)
    return Response.json({"created": body}, status=201)
