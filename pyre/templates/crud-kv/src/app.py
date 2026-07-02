"""A CRUD API over pyre.data collections — records survive upgrades.

Rename `items` and edit the schema to fit your app; that's the whole model.
"""

from pyre import App, Request, Response, data

app = App()
app.enable_cors(origins="*")  # tighten to your frontend's origin for prod

items = data.collection(
    "items",
    schema={
        "name": str,
        "qty": (int, 1),
        "note": (str, ""),
    },
)


@app.get("/health", certified=True)
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})


@app.get("/items")
def list_items(req: Request) -> Response:
    page = items.list(
        limit=int(req.query.get("limit", "20")),
        after=req.query.get("after"),
    )
    return Response.json(page)


@app.post("/items")
def create_item(req: Request) -> Response:
    created = items.insert(req.json())  # schema-validated; bad input → 400
    return Response.json(created, status=201)


@app.get("/items/{id}")
def get_item(req: Request) -> Response:
    item = items.get(req.path_params["id"])
    if item is None:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(item)


@app.put("/items/{id}")
def update_item(req: Request) -> Response:
    try:
        return Response.json(items.update(req.path_params["id"], req.json()))
    except KeyError:
        return Response.json({"error": "not found"}, status=404)


@app.delete("/items/{id}")
def delete_item(req: Request) -> Response:
    if not items.delete(req.path_params["id"]):
        return Response.json({"error": "not found"}, status=404)
    return Response.json({"deleted": req.path_params["id"]})
