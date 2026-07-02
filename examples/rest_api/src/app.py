"""Example A — REST API with persistence (requirements §7).

v1.1 additions: /attest issues a threshold-signed JWT (pyre.sign) —
no private key exists anywhere; the subnet signs cooperatively.
"""

from pyre import App, Request, Response
from pyre import kv, log, sign

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


@app.get("/attest", update=True)  # threshold signing is an async system call
async def attest(req: Request) -> Response:
    token = await sign.jwt({"sub": req.caller or "anonymous", "iss": "pyre-rest-api"})
    log.info("attestation issued", sub=req.caller or "anonymous")
    return Response.json({"jwt": token, "alg": "ES256K"})


@app.get("/attest/pubkey", update=True)
async def attest_pubkey(req: Request) -> Response:
    pub = await sign.public_key()
    return Response.json({"public_key_hex": pub.hex(), "curve": "secp256k1"})
