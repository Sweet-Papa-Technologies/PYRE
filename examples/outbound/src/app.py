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
