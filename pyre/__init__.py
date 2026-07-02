"""PYRE — Python Runtime for the Edge.

Flask-flavored Python on the Internet Computer.

    from pyre import App, Request, Response, kv

    app = App()

    @app.get("/health")
    def health(req: Request) -> Response:
        return Response.json({"status": "ok"})
"""

from pyre._runtime import in_canister
from pyre.application import App
from pyre.errors import (
    BadRequest,
    KvWriteInQueryContext,
    OutcallFailed,
    OutcallInQueryContext,
    PyreError,
    ResponseTooLarge,
    UpstreamHTTPError,
)
from pyre.http_types import Request, Response
from pyre.validation import ValidationError, validate
from pyre import auth
from pyre import data
from pyre import kv

__version__ = "0.1.0"

__all__ = [
    "App",
    "Request",
    "Response",
    "kv",
    "auth",
    "data",
    "validate",
    "ValidationError",
    "in_canister",
    "PyreError",
    "BadRequest",
    "KvWriteInQueryContext",
    "OutcallInQueryContext",
    "OutcallFailed",
    "ResponseTooLarge",
    "UpstreamHTTPError",
]

if in_canister():
    from pyre.compat._stubs import install_stubs

    install_stubs()
