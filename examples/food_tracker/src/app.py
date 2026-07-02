"""Food tracker — PYRE's reference app (WS-D dogfood).

Demonstrates the whole v1.0 surface working together:
  - pyre.data collection with schema validation + pagination
  - API-key auth (hashed token in code; swap for kv-stored hashes)
  - CORS for a browser frontend
  - a PUBLIC, CERTIFIED summary endpoint — anyone can cryptographically
    verify the stats without trusting the gateway

Try it:
    pyre dev examples/food_tracker/src/app.py
    curl -X POST -H "authorization: Bearer demo-food-token" \
         -d '{"name":"apple","kcal":95}' http://127.0.0.1:8000/foods
    curl http://127.0.0.1:8000/summary
"""

import hashlib

from pyre import App, Request, Response, auth, data

app = App()
app.enable_cors(origins="*")

foods = data.collection(
    "foods",
    schema={
        "name": str,
        "kcal": int,
        "protein_g": (float, 0.0),
        "meal": (str, "snack"),  # breakfast / lunch / dinner / snack
    },
)

# Writes need a token; reads of /health and /summary stay public.
# The token itself never lives in canister state — only its hash does.
_TOKEN_HASH = hashlib.sha256(b"demo-food-token").hexdigest()

app.before_request(
    auth.require_token(
        valid=lambda t: hashlib.sha256(t.encode()).hexdigest() == _TOKEN_HASH,
        exempt=("/health", "/summary"),
    )
)


@app.get("/health", certified=True)
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})


@app.get("/summary", certified=True)
def summary(req: Request) -> Response:
    """Public, certified stats — recomputed and re-certified on every write."""
    page = foods.list(limit=10_000)
    total_kcal = sum(f["kcal"] for f in page["items"])
    return Response.json(
        {
            "entries": len(page["items"]),
            "total_kcal": total_kcal,
            "by_meal": _count_by_meal(page["items"]),
        }
    )


def _count_by_meal(items):
    counts = {}
    for item in items:
        counts[item["meal"]] = counts.get(item["meal"], 0) + 1
    return counts


@app.get("/foods")
def list_foods(req: Request) -> Response:
    where = {"meal": req.query["meal"]} if "meal" in req.query else None
    return Response.json(
        foods.list(
            limit=int(req.query.get("limit", "20")),
            after=req.query.get("after"),
            where=where,
        )
    )


@app.post("/foods")
def add_food(req: Request) -> Response:
    return Response.json(foods.insert(req.json()), status=201)


@app.get("/foods/{id}")
def get_food(req: Request) -> Response:
    item = foods.get(req.path_params["id"])
    if item is None:
        return Response.json({"error": "not found"}, status=404)
    return Response.json(item)


@app.put("/foods/{id}")
def update_food(req: Request) -> Response:
    try:
        return Response.json(foods.update(req.path_params["id"], req.json()))
    except KeyError:
        return Response.json({"error": "not found"}, status=404)


@app.delete("/foods/{id}")
def delete_food(req: Request) -> Response:
    if not foods.delete(req.path_params["id"]):
        return Response.json({"error": "not found"}, status=404)
    return Response.json({"deleted": req.path_params["id"]})
