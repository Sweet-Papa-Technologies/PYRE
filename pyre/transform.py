"""The default determinism transform for HTTPS outcalls (requirements §5.1).

ICP replicas each perform the outbound HTTP call independently and must
agree byte-for-byte on the result. Upstream responses almost always differ
per replica in volatile headers (Date, Set-Cookie, request IDs, CDN trace
headers...). The transform function runs on each replica and must map all
of those slightly-different responses onto one canonical value.

PYRE's default transform is an **allowlist**:

  KEEP:   content-type, content-encoding
  STRIP:  every other header (date, server, set-cookie, etag, age,
          cf-ray, x-request-id, x-amzn-*, ... — everything)
  NORMALIZE: kept header names lowercased, headers sorted by name
  BODY:   passed through untouched (if the upstream BODY itself is
          nondeterministic, supply a custom transform)

An allowlist is the only safe default: new volatile headers appear all the
time, and one missed header means consensus failure on mainnet.
"""

# Headers preserved by the default transform. Everything else is stripped.
KEEP_HEADERS = ("content-type", "content-encoding")


def transform_management_response(response):
    """Canonicalize a management-canister HttpResponse dict.

    `response` has the shape {"status": nat, "headers": [{"name","value"}],
    "body": bytes} — the ICP management canister's HttpResponse record.
    Returns the same shape, canonicalized. Used both as the canister-side
    transform implementation and by `pyre dev` to mirror deploy behavior.
    """
    kept = []
    for header in response["headers"]:
        name = header["name"].lower()
        if name in KEEP_HEADERS:
            kept.append({"name": name, "value": header["value"]})
    kept.sort(key=lambda h: h["name"])
    return {
        "status": response["status"],
        "headers": kept,
        "body": response["body"],
    }


def stripped_header_names(headers):
    """Names the default transform would strip — for the `pyre dev` warning."""
    stripped = []
    for header in headers:
        name = header["name"].lower()
        if name not in KEEP_HEADERS:
            stripped.append(name)
    return sorted(set(stripped))
