"""PYRE canister entrypoint — Kybra glue for the static-serving demo.

Standard `pyre new` shape: nothing asset-specific here. pyre.static stores
chunked assets in the same pyre_kv_store stable structure (keyed under
"static:"), and uploads arrive over ordinary HTTP routes registered by
static.admin_routes() — so the gateway's normal update path handles them,
recertifying after each finalize.
"""

from kybra import (
    Alias,
    Async,
    Func,
    Opt,
    Query,
    Record,
    StableBTreeMap,
    Tuple,
    Variant,
    Vec,
    blob,
    init,
    nat16,
    post_upgrade,
    query,
    update,
    void,
)
from kybra.canisters.management import HttpResponse, HttpTransformArgs

import pyre.kv
from pyre.gateway import dispatch_query, dispatch_update
from pyre.transform import transform_management_response

from app import app

# pyre.kv's stable-memory backing — also holds the chunked asset store.
pyre_kv_store = StableBTreeMap[str, str](
    memory_id=250, max_key_size=1_024, max_value_size=64_000
)
pyre.kv.bind_backend(pyre_kv_store)


# --- ICP HTTP gateway Candid interface ------------------------------------


class Token(Record):
    arbitrary_data: str


class StreamingCallbackHttpResponse(Record):
    body: blob
    token: Opt[Token]


Callback = Func(Query[[Token], StreamingCallbackHttpResponse])


class CallbackStrategy(Record):
    callback: Callback
    token: Token


class StreamingStrategy(Variant, total=False):
    Callback: CallbackStrategy


HeaderField = Alias[Tuple[str, str]]


class HttpGatewayRequest(Record):
    method: str
    url: str
    headers: Vec[HeaderField]
    body: blob


class HttpGatewayResponse(Record):
    status_code: nat16
    headers: Vec[HeaderField]
    body: blob
    streaming_strategy: Opt[StreamingStrategy]
    upgrade: Opt[bool]


# --- canister methods -------------------------------------------------------


@init
def pyre_init() -> void:
    app.recertify()


@post_upgrade
def pyre_post_upgrade() -> void:
    app.recertify()


@query
def http_request(req: HttpGatewayRequest) -> HttpGatewayResponse:
    return dispatch_query(app, req)


@update
def http_request_update(req: HttpGatewayRequest) -> Async[HttpGatewayResponse]:
    return (yield from dispatch_update(app, req))


@query
def pyre_default_transform(args: HttpTransformArgs) -> HttpResponse:
    return transform_management_response(args["response"])
