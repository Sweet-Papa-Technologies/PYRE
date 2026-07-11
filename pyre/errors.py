"""Typed PYRE errors.

Every restriction of the ICP platform that PYRE surfaces gets its own
exception type with an actionable message — a clear failure beats a
cryptic canister trap (see requirements §5.6, §6.2).
"""


class PyreError(Exception):
    """Base class for all PYRE errors."""
    code = "PYRE-ERROR"


class BadRequest(PyreError):
    """The inbound HTTP request is malformed (e.g. invalid JSON body).

    Raised by Request.json(); the dispatcher converts it to a 400 response.
    """
    code = "PYRE-BAD-REQUEST"


class KvWriteInQueryContext(PyreError):
    """pyre.kv was written from a query-context handler.

    Query calls on ICP cannot persist state. Mark the route with
    update=True (POST/PUT/DELETE routes are updates by default).
    """
    code = "PYRE-KV-QUERY-WRITE"


class OutcallInQueryContext(PyreError):
    """An HTTPS outcall was attempted from a query-context handler.

    Outcalls can only run in update calls. Mark the route with update=True.
    """
    code = "PYRE-OUTCALL-QUERY"


class ResponseTooLarge(PyreError):
    """The upstream response exceeded max_response_bytes.

    Raise the max_response_bytes argument to urlopen (each byte costs
    cycles, so keep it as low as your upstream allows).
    """
    code = "PYRE-OUTCALL-RESPONSE-LARGE"


class OutcallFailed(PyreError):
    """The HTTPS outcall was rejected or failed (network, consensus, cycles)."""
    code = "PYRE-OUTCALL-FAILED"


class UpstreamHTTPError(PyreError):
    """Upstream returned a non-2xx status and raise_for_status=True was set."""
    code = "PYRE-UPSTREAM-HTTP"

    def __init__(self, status, response=None):
        super().__init__("upstream returned HTTP %s" % status)
        self.status = status
        self.response = response
