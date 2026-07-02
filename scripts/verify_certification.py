#!/usr/bin/env python3
"""Independently verify a PYRE certified response, off-chain.

Usage: verify_certification.py <url> <canister_id>

Performs the HTTP-gateway response-verification v2 procedure:
  1. GET the URL, extract IC-Certificate / IC-CertificateExpression headers
  2. decode certificate, tree, expr_path (base64 + CBOR)
  3. recompute the response hash from the actual wire response
  4. confirm the tree has expr_hash at expr_path and ["", response_hash] -> leaf ""
  5. recompute the witness root and compare it against the canister's
     certified_data revealed inside the certificate
  6. check the certificate /time is recent

NOT checked here: the BLS signature chain to the NNS root key (needs a
bls12-381 pairing library; gateways do check it — on mainnet icp0.io is the
final oracle). Everything else is the real algorithm, implemented
independently of the response producer's code path where it matters
(decoding + tree walking use cbor2, not pyre).

Run from .venv-dev (needs: pip install cbor2).
"""

import base64
import hashlib
import json
import re
import sys
import time
import urllib.request

import cbor2

sys.path.insert(0, ".")  # allow running from repo root
from pyre.certification import hash_of_map, leb128_u  # reuse only the hashers


def sha256(b):
    return hashlib.sha256(b).digest()


def b64field(header_value, name):
    m = re.search(name + r"=:([^:]*):", header_value)
    if not m:
        raise SystemExit("FAIL: field %r missing from IC-Certificate header" % name)
    return base64.b64decode(m.group(1))


# --- hash tree (independent implementation over cbor2 arrays) ---------------


def tree_digest(node):
    tag = node[0]
    ds = lambda s: bytes([len(s)]) + s.encode()
    if tag == 0:
        return sha256(ds("ic-hashtree-empty"))
    if tag == 1:
        return sha256(ds("ic-hashtree-fork") + tree_digest(node[1]) + tree_digest(node[2]))
    if tag == 2:
        return sha256(ds("ic-hashtree-labeled") + node[1] + tree_digest(node[2]))
    if tag == 3:
        return sha256(ds("ic-hashtree-leaf") + node[1])
    if tag == 4:
        return node[1]
    raise SystemExit("FAIL: unknown tree node tag %r" % tag)


def lookup(node, path):
    """Returns the subtree at path, or None."""
    if not path:
        return node
    tag = node[0]
    if tag == 1:
        return lookup(node[1], path) or lookup(node[2], path)
    if tag == 2 and node[1] == path[0]:
        return lookup(node[2], path[1:])
    return None


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    url, canister_id = sys.argv[1], sys.argv[2]
    connect = sys.argv[3] if len(sys.argv) == 4 else None  # e.g. 127.0.0.1:4943

    if connect:
        # python's resolver can't do <id>.raw.localhost — connect directly
        # and pass the virtual host via the Host header
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        fetch_url = urlunsplit((parts.scheme, connect, parts.path, parts.query, ""))
        request = urllib.request.Request(fetch_url, method="GET", headers={"Host": parts.netloc})
    else:
        request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        status = response.status
        headers = response.getheaders()

    hdrs = {k.lower(): v for k, v in headers}
    cert_header = hdrs.get("ic-certificate")
    expr = hdrs.get("ic-certificateexpression")
    if not cert_header or not expr:
        raise SystemExit("FAIL: IC-Certificate / IC-CertificateExpression headers absent")

    certificate = cbor2.loads(b64field(cert_header, "certificate"))
    tree = cbor2.loads(b64field(cert_header, "tree"))
    expr_path = cbor2.loads(b64field(cert_header, "expr_path"))
    version = re.search(r"version=(\d+)", cert_header).group(1)
    assert version == "2", "expected version 2"
    print("expr_path:", expr_path)

    # -- expr hash present at expr_path
    expr_hash = sha256(expr.encode())
    path_labels = [seg.encode() for seg in expr_path]
    expr_node = lookup(tree, path_labels + [expr_hash])
    if expr_node is None:
        raise SystemExit("FAIL: expr_hash not found at expr_path in tree")
    print("expr_hash found at expr_path: OK")

    if "no_certification" in expr:
        print("expression is skip-certification: response body is NOT certified (by design)")
    else:
        # -- recompute response hash from the wire
        m = re.search(r'headers:\[([^\]]*)\]', expr)
        certified = [h.strip('"') for h in m.group(1).split(",") if h] if m else []
        entries = [(name, hdrs[name]) for name in certified if name in hdrs]
        entries.append(("ic-certificateexpression", expr))
        response_hash = sha256(
            hash_of_map_with_status(entries, status) + sha256(body)
        )
        leaf = lookup(expr_node, [b"", response_hash])
        # cbor2 may decode arrays as tuples — compare structurally
        if leaf is None or list(leaf) != [3, b""]:
            raise SystemExit("FAIL: [\"\" , response_hash] leaf not found — body/headers do not match certification")
        print("response hash matches certified leaf: OK")

    # -- witness root vs certified_data in certificate
    root = tree_digest(tree)
    cert_tree = certificate["tree"]
    cd_path = [b"canister", principal_bytes(canister_id), b"certified_data"]
    cd_node = lookup(cert_tree, cd_path)
    if cd_node is None or cd_node[0] != 3:
        raise SystemExit("FAIL: certified_data for %s not revealed in certificate" % canister_id)
    if cd_node[1] != root:
        raise SystemExit("FAIL: witness root != canister certified_data")
    print("witness root == certified_data in certificate: OK")

    # -- time freshness
    time_node = lookup(cert_tree, [b"time"])
    cert_time_ns = leb128_decode(time_node[1])
    age = abs(time.time() - cert_time_ns / 1e9)
    print("certificate age: %.1fs %s" % (age, "OK" if age < 300 else "STALE"))
    if age >= 300:
        raise SystemExit("FAIL: certificate is stale")

    print("delegation present:", "delegation" in certificate,
          "(BLS signature chain not checked here — gateways enforce it)")
    print("PASS: response verification v2 checks succeeded")


def hash_of_map_with_status(entries, status):
    all_entries = list(entries) + [(":ic-cert-status", int(status))]
    return hash_of_map(all_entries)


def leb128_decode(data):
    result = 0
    for i, byte in enumerate(data):
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            break
    return result


def principal_bytes(text):
    text = text.replace("-", "").upper()
    # base32 decode (RFC 4648, no padding); first 4 bytes are CRC32
    pad = "=" * (-len(text) % 8)
    raw = base64.b32decode(text + pad)
    return raw[4:]


if __name__ == "__main__":
    main()
