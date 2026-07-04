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
from pyre import crypto
from pyre import data
from pyre import kv
from pyre import log
from pyre import oidc
from pyre import sign
from pyre import static
from pyre import ptime
from pyre import prandom  # imports ptime; keep after it
from pyre import puuid

# DX aliases (§v1.1 randomness/time). The real module files are
# prandom/ptime/puuid — files named random.py/uuid.py/time.py would shadow
# the stdlib inside the Kybra bundle. These attribute aliases make the
# documented spelling work:
#
#     from pyre import random as prandom
#     from pyre import time as ptime
#     from pyre import uuid as puuid
#
# Note: only the `from pyre import ...` form works; the statement form
# `import pyre.random` will raise ModuleNotFoundError because there is no
# pyre/random.py file — that is deliberate.
random = prandom
time = ptime
uuid = puuid

__version__ = "1.2.1"

__all__ = [
    "App",
    "Request",
    "Response",
    "kv",
    "auth",
    "crypto",
    "data",
    "log",
    "oidc",
    "sign",
    "static",
    "random",
    "time",
    "uuid",
    "prandom",
    "ptime",
    "puuid",
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
