"""A urllib-shaped API over ICP HTTPS outcalls (requirements §6.2).

    from pyre.compat import urllib_request as urllib

    @app.get("/quote", update=True)
    async def quote(req):
        resp = await urllib.urlopen("https://...", max_response_bytes=8_192)
        return Response.json({"status": resp.status, "data": resp.json()})

Differences from the stdlib, imposed by the platform:
  - urlopen is awaitable (outcalls are async + consensus-gated) and only
    works in update-context handlers.
  - Every call goes through a determinism transform (default strips all
    headers except content-type/content-encoding — see pyre.transform).
  - max_response_bytes caps the response; bytes cost cycles.
  - Only GET/HEAD/POST are supported upstream.

This module never monkeypatches the real urllib — explicit import only.
"""

from pyre.errors import (  # noqa: F401 — re-exported for callers
    OutcallFailed,
    OutcallInQueryContext,
    ResponseTooLarge,
    UpstreamHTTPError,
)
from pyre.outcall import (  # noqa: F401
    DEFAULT_CYCLES,
    DEFAULT_MAX_RESPONSE_BYTES,
    OutcallFuture,
    UrlResponse,
)

# The Candid name of the transform query method the canister template
# registers. Pass transform=None to skip transforming (NOT deploy-safe:
# replicas will disagree on volatile headers and the call will fail).
default_transform = "pyre_default_transform"


def urlopen(
    url,
    *,
    method="GET",
    data=None,
    headers=None,
    transform=default_transform,
    max_response_bytes=DEFAULT_MAX_RESPONSE_BYTES,
    cycles=None,
    raise_for_status=False,
):
    """Start an HTTPS outcall. Returns an awaitable OutcallFuture."""
    return OutcallFuture(
        url=url,
        method=method,
        data=data,
        headers=headers,
        transform_name=transform,
        max_response_bytes=max_response_bytes,
        cycles=cycles,
        raise_for_status=raise_for_status,
    )
