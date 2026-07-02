"""Outbound HTTPS via the urllib shim — async handlers in update context.

Two things make outcalls different on ICP (both handled for you):
  - every replica fetches independently, so a transform strips the
    volatile parts before consensus (pyre's default strips all headers
    except content-type/content-encoding);
  - upstream hosts MUST be IPv6-reachable (dig AAAA <host>).
"""

from pyre import App, Request, Response
from pyre.compat import urllib_request as urllib

app = App()

# Only these upstreams may be proxied. An open proxy would let anyone
# spend your canister's cycles.
ALLOWED_HOSTS = ("xkcd.com",)


@app.get("/health", certified=True)
def health(req: Request) -> Response:
    return Response.json({"status": "ok"})


@app.get("/proxy", update=True)  # outcalls require update context
async def proxy(req: Request) -> Response:
    url = req.query.get("url", "")
    parts = url.split("/")
    host = parts[2] if url.startswith("https://") and len(parts) > 2 else ""
    if host not in ALLOWED_HOSTS:
        return Response.json(
            {"error": "host not allowed", "allowed": list(ALLOWED_HOSTS)}, status=403
        )
    resp = await urllib.urlopen(url, max_response_bytes=16_384)
    return Response.json({"upstream_status": resp.status, "data": resp.json()})
