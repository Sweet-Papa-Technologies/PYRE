"""Gateway adapter: ICP http_request/http_request_update dicts ⇄ pyre objects.

This module is deliberately Kybra-free. The canister's main.py declares the
Candid records (see templates/examples) and passes the plain dicts here.
Keeping the CDK surface confined to main.py + OutcallFuture._to_kybra_call
keeps the runtime layer thin and swappable (requirements §4.1).

Gateway request dict:  {"method", "url", "headers": [(k, v)...], "body": blob}
Gateway response dict: {"status_code", "headers": [(k, v)...], "body": blob,
                        "streaming_strategy": None, "upgrade": Opt[bool]}
"""

from pyre.application import UPGRADE
from pyre.http_types import Request


def request_from_gateway(req):
    url = req["url"] or "/"
    path, _, query_string = url.partition("?")
    headers = {}
    for name, value in req["headers"]:
        headers[name] = value
    request = Request(
        method=req["method"],
        path=path or "/",
        headers=headers,
        query_string=query_string,
        body=req["body"] or b"",
    )
    # Caller principal (anonymous "2vxsx-fae" for plain HTTP-gateway traffic;
    # meaningful when called through an authenticated agent). None on host.
    try:
        from kybra import ic

        request.caller = ic.caller().to_str()
    except Exception:
        request.caller = None
    return request


def response_to_gateway(response, upgrade=None):
    return {
        "status_code": response.status,
        "headers": list(response.headers),
        "body": response.body,
        "streaming_strategy": None,
        "upgrade": upgrade,
    }


_UPGRADE_RESPONSE = {
    "status_code": 204,
    "headers": [],
    "body": b"",
    "streaming_strategy": None,
    "upgrade": True,
}


def dispatch_query(app, req):
    """Body of the canister's http_request query method."""
    request = request_from_gateway(req)
    result = app.handle_query(request)
    if result is UPGRADE:
        return dict(_UPGRADE_RESPONSE)
    out = response_to_gateway(result)
    if app._certification_active and app.certification is not None:
        import pyre.certification

        certificate = pyre.certification.data_certificate()
        if request.path in app.certification.responses:
            extra = app.certification.certificate_headers(request.path, certificate)
        else:
            extra = app.certification.skip_headers(certificate)
        out["headers"] = list(out["headers"]) + extra
    return out


def dispatch_update(app, req):
    """Body of the canister's http_request_update update method (generator).

    Use as: `return (yield from dispatch_update(app, req))`.
    """
    response = yield from app.handle_update(request_from_gateway(req))
    if app.certification is not None or app.has_certified_routes():
        # State may have changed: re-render certified snapshots and commit
        # the new tree root while still in update context.
        try:
            app.recertify()
        except Exception as e:  # noqa: BLE001 — surface loudly, don't hide
            from pyre.http_types import Response

            response = Response.json(
                {
                    "error": "certification failure",
                    "message": "update succeeded but re-certifying failed: %s" % e,
                },
                status=500,
            )
    return response_to_gateway(response)
