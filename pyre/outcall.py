"""HTTPS-outcall plumbing: OutcallFuture, UrlResponse, and the pump.

Kybra's async model is generator-based: an update method `yield`s a
management-canister call and Kybra sends the CallResult back in. PYRE
handlers instead write either

    async def handler(req):                  # spec style (§7 Example B)
        resp = await urllib.urlopen(...)

or the equivalent generator style

    def handler(req):
        resp = yield urllib.urlopen(...)

`urlopen` returns an OutcallFuture. The pump below sits between the user
handler and Kybra: it drives the handler (coroutines and generators expose
the same .send/.throw protocol), converts each OutcallFuture into a real
management-canister call, yields that up to Kybra, converts the CallResult
into a UrlResponse (or a typed error thrown into the handler), and sends
it back down.
"""

import json as _json

from pyre._runtime import ctx
from pyre.errors import (
    OutcallFailed,
    OutcallInQueryContext,
    PyreError,
    ResponseTooLarge,
    UpstreamHTTPError,
)

# ICP HTTPS outcalls support only these upstream methods.
SUPPORTED_METHODS = ("GET", "HEAD", "POST")

# Cycles attached to each outcall. Excess cycles are refunded by the
# management canister, so the default is deliberately generous.
DEFAULT_CYCLES = 3_000_000_000

# Conservative default response cap (each allowed byte costs cycles).
DEFAULT_MAX_RESPONSE_BYTES = 16_384

# Error substrings the replica uses for oversized responses (best effort).
_SIZE_ERROR_MARKERS = ("max_response_bytes", "body exceeds size limit", "response is too large")


class UrlResponse:
    """What `await urlopen(...)` evaluates to. urllib-addinfourl-flavored."""

    def __init__(self, status, headers, body, url):
        self.status = int(status)
        # dict with lowercased names (post-transform there are few)
        self.headers = headers
        self._body = bytes(body)
        self.url = url

    def read(self):
        return self._body

    def json(self):
        return _json.loads(self._body.decode("utf-8"))

    def text(self):
        return self._body.decode("utf-8")

    def __repr__(self):
        return "<UrlResponse %s %s (%d bytes)>" % (self.status, self.url, len(self._body))


class OutcallFuture:
    """A pending HTTPS outcall. Await it (or yield it) inside a handler."""

    def __init__(self, url, method, data, headers, transform_name,
                 max_response_bytes, cycles, raise_for_status):
        method = method.upper()
        if method not in SUPPORTED_METHODS:
            raise PyreError(
                "ICP HTTPS outcalls support only GET/HEAD/POST upstream; got %s" % method
            )
        if ctx.in_query:
            raise OutcallInQueryContext(
                "HTTPS outcalls need update context; mark the route update=True "
                "(route %s runs as a query)" % url
            )
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.url = url
        self.method = method
        self.data = data
        self.headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.transform_name = transform_name
        self.max_response_bytes = int(max_response_bytes)
        self.cycles = DEFAULT_CYCLES if cycles is None else int(cycles)
        self.raise_for_status = bool(raise_for_status)

    def __await__(self):
        result = yield self
        return result

    # allow `yield from fut` in generator-style handlers too
    __iter__ = __await__

    # -- canister side -----------------------------------------------------

    def _to_kybra_call(self):
        """Build the real management-canister call (canister runtime only)."""
        from kybra import ic  # imported lazily: host CPython never gets here
        from kybra.canisters.management import management_canister

        transform = None
        if self.transform_name:
            transform = {
                "function": (ic.id(), self.transform_name),
                "context": bytes(),
            }
        args = {
            "url": self.url,
            "max_response_bytes": self.max_response_bytes,
            "method": {self.method.lower(): None},
            "headers": [{"name": k, "value": v} for k, v in self.headers.items()],
            "body": self.data,
            "transform": transform,
        }
        return management_canister.http_request(args).with_cycles(self.cycles)

    def _process_call_result(self, call_result):
        """CallResult[HttpResponse] → UrlResponse, or raise a typed error."""
        err = _variant_get(call_result, "Err")
        if err is not None:
            message = str(err)
            lowered = message.lower()
            if any(marker in lowered for marker in _SIZE_ERROR_MARKERS):
                raise ResponseTooLarge(
                    "upstream response exceeded max_response_bytes=%d: %s"
                    % (self.max_response_bytes, message)
                )
            hint = ""
            if any(m in lowered for m in ("connecting to", "dns error", "timed out", "connect")):
                hint = (
                    " — HINT: ICP replicas reach the internet over IPv6 only; if this "
                    "host has no AAAA DNS record the call can never succeed. Verify "
                    "with: dig AAAA <host>"
                )
            raise OutcallFailed("HTTPS outcall to %s failed: %s%s" % (self.url, message, hint))
        response = _variant_get(call_result, "Ok")
        return self._wrap_response(response)

    def _wrap_response(self, response):
        """management HttpResponse dict → UrlResponse (shared with dev mode)."""
        headers = {h["name"].lower(): h["value"] for h in response["headers"]}
        result = UrlResponse(response["status"], headers, response["body"], self.url)
        if self.raise_for_status and result.status >= 400:
            raise UpstreamHTTPError(result.status, response=result)
        return result


def _variant_get(call_result, key):
    """CallResult may be an object with .Ok/.Err or a dict; handle both."""
    if isinstance(call_result, dict):
        return call_result.get(key)
    return getattr(call_result, key, None)


def is_pumpable(obj):
    """True for generator or coroutine objects (both expose send/throw)."""
    return hasattr(obj, "send") and hasattr(obj, "throw")


def pump(handler_result):
    """Drive a handler generator/coroutine inside a Kybra update method.

    This is itself a generator: it yields Kybra call objects upward and
    receives CallResults back. Use as `rv = yield from pump(h)`.
    """
    if not is_pumpable(handler_result):
        return handler_result

    to_send = None
    pending_exc = None
    while True:
        try:
            if pending_exc is not None:
                exc, pending_exc = pending_exc, None
                yielded = handler_result.throw(exc)
            else:
                yielded = handler_result.send(to_send)
        except StopIteration as stop:
            return getattr(stop, "value", None)

        if isinstance(yielded, OutcallFuture):
            call_result = yield yielded._to_kybra_call()
            try:
                to_send = yielded._process_call_result(call_result)
            except PyreError as e:
                to_send = None
                pending_exc = e
        else:
            # Raw Kybra calls pass straight through (escape hatch).
            to_send = yield yielded


def pump_sync(handler_result, resolve):
    """Drive a handler synchronously, resolving OutcallFutures via `resolve`.

    Used by `pyre dev` (real HTTP) and by unit tests (fakes).
    """
    if not is_pumpable(handler_result):
        return handler_result

    to_send = None
    pending_exc = None
    while True:
        try:
            if pending_exc is not None:
                exc, pending_exc = pending_exc, None
                yielded = handler_result.throw(exc)
            else:
                yielded = handler_result.send(to_send)
        except StopIteration as stop:
            return getattr(stop, "value", None)

        if isinstance(yielded, OutcallFuture):
            try:
                to_send = resolve(yielded)
            except PyreError as e:
                to_send = None
                pending_exc = e
        else:
            raise PyreError(
                "handler yielded %r — only OutcallFutures can be awaited in dev mode"
                % (yielded,)
            )
