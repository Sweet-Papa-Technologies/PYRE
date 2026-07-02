"""Phase 1 — HTTPS-outcall determinism spike (GO/NO-GO gate, §8).

Framework-free by design: this talks to the management canister directly
so the gate result reflects the platform, not PYRE code.

  fetch_transformed(url)      — outcall through spike_transform (header allowlist)
  fetch_raw(url)              — outcall with NO transform (failure-mode probe)
  fetch_json_normalized(url, fields)
                              — header allowlist PLUS body-level JSON
                                normalization: blanks the named volatile
                                fields (comma-separated dotted paths, passed
                                via the transform's context blob) and
                                re-serializes canonically. This is the fix
                                for endpoints whose BODY differs per replica
                                (uuids, server timestamps).

All return a canonical string (status | sorted headers | body sha256) so
repeated calls can be byte-compared by the gate scripts.
"""

import hashlib
import json

from kybra import Async, CallResult, ic, match, nat64, query, update
from kybra.canisters.management import (
    HttpResponse,
    HttpTransformArgs,
    management_canister,
)

CYCLES = 3_000_000_000
MAX_RESPONSE_BYTES = 8_192

# Same allowlist as pyre.transform (duplicated: the spike must not import pyre).
KEEP_HEADERS = ("content-type", "content-encoding")


def _canonical(response) -> str:
    headers = ";".join(
        sorted("%s=%s" % (h["name"], h["value"]) for h in response["headers"])
    )
    body = response["body"]
    return "status=%s|headers=[%s]|body_sha256=%s|body_len=%d" % (
        response["status"],
        headers,
        hashlib.sha256(body).hexdigest(),
        len(body),
    )


def _http_get(url: str, transform_name: str = "", context: bytes = b""):
    transform = None
    if transform_name:
        transform = {"function": (ic.id(), transform_name), "context": context}
    return management_canister.http_request(
        {
            "url": url,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "method": {"get": None},
            "headers": [],
            "body": None,
            "transform": transform,
        }
    ).with_cycles(CYCLES)


@update
def fetch_transformed(url: str) -> Async[str]:
    result: CallResult[HttpResponse] = yield _http_get(url, "spike_transform")
    return match(result, {"Ok": _canonical, "Err": lambda err: "ERR:%s" % err})


@update
def fetch_raw(url: str) -> Async[str]:
    result: CallResult[HttpResponse] = yield _http_get(url)
    return match(result, {"Ok": _canonical, "Err": lambda err: "ERR:%s" % err})


@update
def fetch_json_normalized(url: str, volatile_fields: str) -> Async[str]:
    """volatile_fields: comma-separated dotted paths to blank, e.g. 'uuid,meta.ts'."""
    result: CallResult[HttpResponse] = yield _http_get(
        url, "spike_json_transform", volatile_fields.encode("utf-8")
    )
    return match(result, {"Ok": _canonical, "Err": lambda err: "ERR:%s" % err})


def _keep_headers(response):
    kept = [
        {"name": h["name"].lower(), "value": h["value"]}
        for h in response["headers"]
        if h["name"].lower() in KEEP_HEADERS
    ]
    kept.sort(key=lambda h: h["name"])
    return kept


def _blank_path(obj, path):
    for key in path[:-1]:
        if isinstance(obj, dict) and key in obj:
            obj = obj[key]
        else:
            return
    if isinstance(obj, dict) and path[-1] in obj:
        obj[path[-1]] = None


@query
def spike_transform(args: HttpTransformArgs) -> HttpResponse:
    response = args["response"]
    return {
        "status": response["status"],
        "headers": _keep_headers(response),
        "body": response["body"],
    }


@query
def spike_json_transform(args: HttpTransformArgs) -> HttpResponse:
    """Header allowlist + blank volatile JSON body fields + canonical dump."""
    response = args["response"]
    body = response["body"]
    fields = args["context"].decode("utf-8") if args["context"] else ""
    try:
        data = json.loads(bytes(body).decode("utf-8"))
        for dotted in fields.split(","):
            dotted = dotted.strip()
            if dotted:
                _blank_path(data, dotted.split("."))
        body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeDecodeError):
        pass  # not JSON — leave the body alone; header transform still applies
    return {
        "status": response["status"],
        "headers": _keep_headers(response),
        "body": body,
    }


@query
def perf_baseline() -> nat64:
    """Instructions for a trivial query — §5.4 baseline measurement."""
    return ic.performance_counter(0)
