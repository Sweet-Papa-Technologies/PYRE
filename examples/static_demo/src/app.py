"""Example — serve a built single-page app from the canister, CERTIFIED.

`pyre.static` turns the canister into a static host for a Vue/Vite `dist/`
you upload with `pyre assets push`. index.html is served as a v2-certified
query response carrying an IC-Certificate; other assets serve from the
chunked stable-memory store with correct content-types and gzip. Unknown
client routes fall back to index.html so the SPA router works on refresh.

Upload:  pyre assets push dist/ --url http://<canister>.localhost:4943 \
                                --token demo-static-token
"""

from pyre import App, Request, Response
from pyre import static

app = App()
app.enable_cors(origins="*")

# Bearer token guarding the asset-upload routes (demo only — store a hash
# in real apps, same as pyre.auth guidance).
UPLOAD_TOKEN = "demo-static-token"


@app.get("/api/health")
def health(req: Request) -> Response:
    # A normal API route: registered routes always win over static serving.
    return Response.json({"status": "ok", "service": "static_demo"})


# Upload protocol at /_pyre/static/{manifest,chunk,finalize,delete,list}.
static.admin_routes(app, UPLOAD_TOKEN)

# Serve the uploaded SPA at "/", certified index, SPA fallback for client
# routes. Register LAST — the catch-all yields to every route above.
static.mount(app, prefix="/", index="index.html", spa=True, certified_index=True)
