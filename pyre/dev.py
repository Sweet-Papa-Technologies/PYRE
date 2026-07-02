"""`pyre dev` — instant local iteration without a replica (§4.2).

Hosts the same App object behind a stdlib HTTP server, driving the exact
same routing/dispatch code paths as the canister gateway adapter. Query
restrictions are enforced (kv writes / outcalls from query routes raise),
so ICP surprises show up before deploy.

Outcalls perform real HTTP here, then run through the same default
transform used on-chain, and log a warning listing which headers the
transform stripped — determinism surprises surface early.
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pyre.errors import OutcallFailed, ResponseTooLarge
from pyre.gateway import request_from_gateway, response_to_gateway
from pyre.transform import stripped_header_names, transform_management_response


def _log(message):
    sys.stderr.write("pyre dev: %s\n" % message)


def resolve_outcall_dev(fut):
    """Resolve an OutcallFuture with real HTTP + the on-chain transform.

    Non-HTTP management futures (pyre.sign, …) carry their own dev
    resolution and never touch the network here.
    """
    if hasattr(fut, "_resolve_dev"):
        return fut._resolve_dev()

    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        fut.url, data=fut.data, headers=fut.headers, method=fut.method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as upstream:
            body = upstream.read(fut.max_response_bytes + 1)
            status = upstream.status
            raw_headers = [{"name": k, "value": v} for k, v in upstream.getheaders()]
    except urllib.error.HTTPError as e:
        # non-2xx still yields a response, mirroring the outcall behavior
        body = e.read(fut.max_response_bytes + 1)
        status = e.code
        raw_headers = [{"name": k, "value": v} for k, v in (e.headers or {}).items()]
    except urllib.error.URLError as e:
        raise OutcallFailed("HTTPS outcall to %s failed: %s" % (fut.url, e.reason))

    if len(body) > fut.max_response_bytes:
        raise ResponseTooLarge(
            "upstream response exceeded max_response_bytes=%d (on ICP this outcall "
            "would be rejected; raise max_response_bytes)" % fut.max_response_bytes
        )

    raw = {"status": status, "headers": raw_headers, "body": body}
    if fut.transform_name:
        stripped = stripped_header_names(raw_headers)
        if stripped:
            _log(
                "default transform will strip these upstream headers on ICP: %s"
                % ", ".join(stripped)
            )
        raw = transform_management_response(raw)
    else:
        _log(
            "WARNING: outcall to %s has transform=None — replicas will see "
            "differing volatile headers and the call will fail on ICP" % fut.url
        )
    return fut._wrap_response(raw)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _dispatch(self):
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            gateway_request = {
                "method": self.command,
                "url": self.path,
                "headers": list(self.headers.items()),
                "body": body,
            }
            request = request_from_gateway(gateway_request)
            response = app.handle_dev(request, resolve_outcall_dev)
            gateway_response = response_to_gateway(response)

            self.send_response(gateway_response["status_code"])
            payload = gateway_response["body"]
            seen = {name.lower() for name, _ in gateway_response["headers"]}
            for name, value in gateway_response["headers"]:
                self.send_header(name, value)
            if "content-length" not in seen:
                self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _dispatch

        def log_message(self, fmt, *args):
            _log("%s %s" % (self.command, self.path))

    return Handler


def serve(app, host="127.0.0.1", port=8000):
    server = ThreadingHTTPServer((host, port), make_handler(app))
    _log("serving on http://%s:%d (Ctrl-C to stop)" % (host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("shutting down")
    finally:
        server.server_close()
