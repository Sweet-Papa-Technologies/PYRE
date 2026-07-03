"""Example B — outbound HTTP via the urllib shim (requirements §7).

Handlers that make outcalls are async and must run in update context.
"""

from pyre import App, Response
from pyre.compat import urllib_request as urllib

app = App()

# A stable public JSON endpoint (fixed comic → deterministic body).
UPSTREAM = "https://xkcd.com/642/info.0.json"


@app.get("/quote", update=True)  # outcalls require update context
async def quote(req):
    resp = await urllib.urlopen(
        UPSTREAM,
        transform=urllib.default_transform,  # strips nondeterministic headers
        max_response_bytes=8_192,
    )
    return Response.json({"upstream_status": resp.status, "data": resp.json()})


# -- v1.1 adapter fan-out gate (Phase-4 mainnet acceptance) -------------------
# One canister write is delivered ~13x upstream (replica fan-out); the
# adapter's client-generated-key upsert must converge to exactly one row.

try:
    from supa_config import SUPA_URL, SUPA_ANON_KEY  # gitignored real config
except ImportError:  # host CPython test runs resolve the package path instead
    try:
        from examples.outbound.src.supa_config import SUPA_URL, SUPA_ANON_KEY
    except ImportError:
        SUPA_URL = SUPA_ANON_KEY = None

if SUPA_URL:
    from pyre import random as prandom, time as ptime
    from pyre.adapters import supabase

    db = supabase.Client(url=SUPA_URL, anon_key=SUPA_ANON_KEY)

    @app.get("/supa/write", update=True)
    async def supa_write(req):
        # Consensus-safe id: every replica computes the SAME uuid, so the
        # ~13 amplified upserts all target one row.
        row = {"id": prandom.uuid4(), "title": "fanout-%d" % ptime.now_ms()}
        await db.table("items").insert(row)
        return Response.json({"wrote": row})

    @app.get("/supa/rows/{id}", update=True)
    async def supa_rows(req):
        rows = await db.table("items").select("id,title").eq(
            "id", req.path_params["id"])
        return Response.json({"count": len(rows), "rows": rows})

    @app.get("/supa/read", update=True)
    async def supa_read(req):
        # order by unique column -> byte-identical bodies across replicas
        rows = await db.table("items").select("id,title").order("id").limit(10)
        return Response.json({"rows": rows})
