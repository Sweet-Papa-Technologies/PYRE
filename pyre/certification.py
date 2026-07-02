"""HTTP response certification v2 (certified reads).

Implements the ICP HTTP-gateway response-verification v2 subprotocol in
pure Python (RustPython-safe, stdlib-only):

  - ic-hashtree construction, root hashing, and CBOR witness encoding
  - representation-independent hashing (hash-of-map, LEB128 numbers)
  - CEL certification expressions (response-only + skip-certification)
  - the IC-Certificate / IC-CertificateExpression response headers

Model: certified routes are GET query routes with static paths whose
responses are re-rendered and re-certified after every update call (state
only changes in updates, so the certified snapshot is always current).
Uncertified routes are covered by a wildcard skip-certification entry so
they remain servable through verifying gateways — with the trust model
documented rather than silently relying on gateway leniency.

Spec: HTTP gateway protocol, "Response Verification" (v2).
"""

import base64
import hashlib

from pyre.errors import PyreError

# ---------------------------------------------------------------------------
# CEL certification expressions (minified — the spec's EBNF forbids spaces)
# ---------------------------------------------------------------------------

SKIP_CERTIFICATION_EXPR = "default_certification(ValidationArgs{no_certification:Empty{}})"


def response_only_expr(certified_headers):
    headers = ",".join('"%s"' % h for h in certified_headers)
    return (
        "default_certification(ValidationArgs{certification:Certification{"
        "no_request_certification:Empty{},"
        "response_certification:ResponseCertification{"
        "certified_response_headers:ResponseHeaderList{headers:[%s]}}}})" % headers
    )


# Headers certified for certified routes (IC-CertificateExpression is always
# included by the spec; IC-Certificate always excluded).
DEFAULT_CERTIFIED_HEADERS = ("content-type",)

# ---------------------------------------------------------------------------
# LEB128 + representation-independent hashing (interface spec "hash of map")
# ---------------------------------------------------------------------------


def leb128_u(n):
    if n < 0:
        raise ValueError("leb128_u needs a non-negative integer")
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _sha256(data):
    return hashlib.sha256(data).digest()


def _hash_value(value):
    if isinstance(value, bool):
        raise ValueError("bool is not hashable in hash-of-map")
    if isinstance(value, int):
        return _sha256(leb128_u(value))
    if isinstance(value, str):
        return _sha256(value.encode("utf-8"))
    if isinstance(value, (bytes, bytearray)):
        return _sha256(bytes(value))
    raise ValueError("unhashable value type: %s" % type(value).__name__)


def hash_of_map(entries):
    """entries: iterable of (name: str, value: str|int|bytes). Order-free."""
    concatenations = []
    for name, value in entries:
        concatenations.append(_sha256(name.encode("utf-8")) + _hash_value(value))
    concatenations.sort()
    return _sha256(b"".join(concatenations))


def response_hash(status, headers, body, expr):
    """Response hash per spec §Response Hash Calculation.

    headers: list of (name, value) — only the CERTIFIED headers (already
    filtered); IC-CertificateExpression and :ic-cert-status are added here.
    """
    entries = [(name.lower(), value) for name, value in headers]
    entries.append(("ic-certificateexpression", expr))
    entries.append((":ic-cert-status", int(status)))
    return _sha256(hash_of_map(entries) + _sha256(body))


# ---------------------------------------------------------------------------
# ic-hashtree: structure, hashing, CBOR encoding
# Nodes: ("empty",) ("fork",l,r) ("labeled",label,sub) ("leaf",data) ("pruned",digest)
# ---------------------------------------------------------------------------


def _domain_sep(s):
    encoded = s.encode("utf-8")
    return bytes([len(encoded)]) + encoded


_DS_EMPTY = _domain_sep("ic-hashtree-empty")
_DS_FORK = _domain_sep("ic-hashtree-fork")
_DS_LABELED = _domain_sep("ic-hashtree-labeled")
_DS_LEAF = _domain_sep("ic-hashtree-leaf")


def tree_hash(node):
    kind = node[0]
    if kind == "empty":
        return _sha256(_DS_EMPTY)
    if kind == "fork":
        return _sha256(_DS_FORK + tree_hash(node[1]) + tree_hash(node[2]))
    if kind == "labeled":
        return _sha256(_DS_LABELED + node[1] + tree_hash(node[2]))
    if kind == "leaf":
        return _sha256(_DS_LEAF + node[1])
    if kind == "pruned":
        return node[1]
    raise PyreError("unknown hash-tree node kind: %r" % (kind,))


def from_labeled_children(children):
    """children: list of (label: bytes, node). Builds a balanced fork spine
    over the label-sorted children (any shape is valid; balanced is standard)."""
    children = sorted(children, key=lambda c: c[0])

    def build(lo, hi):
        if hi - lo == 0:
            return ("empty",)
        if hi - lo == 1:
            label, sub = children[lo]
            return ("labeled", label, sub)
        mid = (lo + hi) // 2
        return ("fork", build(lo, mid), build(mid, hi))

    return build(0, len(children))


def tree_from_paths(paths):
    """paths: list of (labels: list[bytes], leaf_data: bytes) → tree node."""
    root = {}
    for labels, leaf_data in paths:
        cursor = root
        for label in labels[:-1]:
            nxt = cursor.setdefault(label, {})
            if not isinstance(nxt, dict):
                raise PyreError("certification path conflict at %r" % label)
            cursor = nxt
        existing = cursor.get(labels[-1])
        if isinstance(existing, dict) and existing:
            raise PyreError("certification path conflict at %r" % labels[-1])
        cursor[labels[-1]] = ("leaf", leaf_data)

    def materialize(mapping):
        children = []
        for label, sub in mapping.items():
            node = materialize(sub) if isinstance(sub, dict) else sub
            children.append((label, node))
        return from_labeled_children(children)

    return materialize(root)


def prune_for_path(node, labels):
    """Witness: keep the spine down `labels` and everything BELOW the path
    endpoint (the verifier must find e.g. the ["", response_hash] leaf under
    expr_hash); prune subtrees under all other labeled nodes (their labels
    stay visible, proving absence correctly)."""
    if not labels:
        return node  # at/below the path endpoint: reveal fully
    kind = node[0]
    if kind == "fork":
        return ("fork", prune_for_path(node[1], labels), prune_for_path(node[2], labels))
    if kind == "labeled":
        if node[1] == labels[0]:
            return ("labeled", node[1], prune_for_path(node[2], labels[1:]))
        sub = node[2]
        if sub[0] == "leaf" and not sub[1]:
            return node  # empty leaf: cheaper to keep than to prune
        return ("labeled", node[1], ("pruned", tree_hash(sub)))
    return node


# --- minimal CBOR encoder (unsigned ints, bytes, text, arrays, tag) --------


def _cbor_head(major, value):
    if value < 24:
        return bytes([(major << 5) | value])
    for bits, code in ((8, 24), (16, 25), (32, 26), (64, 27)):
        if value < (1 << bits):
            return bytes([(major << 5) | code]) + value.to_bytes(bits // 8, "big")
    raise ValueError("value too large for CBOR")


def cbor_encode(obj):
    if isinstance(obj, int):
        return _cbor_head(0, obj)
    if isinstance(obj, (bytes, bytearray)):
        return _cbor_head(2, len(obj)) + bytes(obj)
    if isinstance(obj, str):
        encoded = obj.encode("utf-8")
        return _cbor_head(3, len(encoded)) + encoded
    if isinstance(obj, (list, tuple)):
        return _cbor_head(4, len(obj)) + b"".join(cbor_encode(x) for x in obj)
    raise ValueError("cannot CBOR-encode %s" % type(obj).__name__)


def cbor_self_describing(obj):
    return _cbor_head(6, 55799) + cbor_encode(obj)


def tree_to_cbor_obj(node):
    kind = node[0]
    if kind == "empty":
        return [0]
    if kind == "fork":
        return [1, tree_to_cbor_obj(node[1]), tree_to_cbor_obj(node[2])]
    if kind == "labeled":
        return [2, node[1], tree_to_cbor_obj(node[2])]
    if kind == "leaf":
        return [3, node[1]]
    if kind == "pruned":
        return [4, node[1]]
    raise PyreError("unknown hash-tree node kind: %r" % (kind,))


# ---------------------------------------------------------------------------
# Expression paths
# ---------------------------------------------------------------------------


def url_segments(path):
    """'/items/all' → ['items', 'all']; '/' → ['']."""
    return path.split("/")[1:] if path.startswith("/") else path.split("/")


def exact_expr_path(path):
    return ["http_expr"] + url_segments(path) + ["<$>"]


WILDCARD_EXPR_PATH = ["http_expr", "<*>"]


# ---------------------------------------------------------------------------
# The certification store used by App
# ---------------------------------------------------------------------------


def _b64(data):
    return base64.b64encode(data).decode("ascii")


class CertifiedStore:
    """Holds certified route snapshots + the current hash tree."""

    def __init__(self, certified_headers=DEFAULT_CERTIFIED_HEADERS):
        self.certified_headers = tuple(h.lower() for h in certified_headers)
        self.expr = response_only_expr(self.certified_headers)
        self.expr_hash = _sha256(self.expr.encode("utf-8"))
        self.skip_expr_hash = _sha256(SKIP_CERTIFICATION_EXPR.encode("utf-8"))
        self.responses = {}  # path -> Response (frozen snapshot)
        self._tree = None
        self._root = None
        # per-path (tree_b64, expr_path_b64) — witnesses only change on
        # rebuild, so they're precomputed there, not per-request (§5.4)
        self._witness_cache = {}

    # -- building -----------------------------------------------------------

    def put(self, path, response):
        self.responses[path] = response

    def rebuild(self):
        """Rebuild the tree from current snapshots. Returns the 32-byte root."""
        paths = [(self._skip_labels(), b"")]
        for path, resp in self.responses.items():
            labels = [seg.encode("utf-8") for seg in exact_expr_path(path)]
            labels.append(self.expr_hash)
            labels.append(b"")
            labels.append(self._response_hash(resp))
            paths.append((labels, b""))
        self._tree = tree_from_paths(paths)
        self._root = tree_hash(self._tree)
        self._witness_cache = {}
        for path in self.responses:
            labels = [seg.encode("utf-8") for seg in exact_expr_path(path)]
            witness = prune_for_path(self._tree, labels + [self.expr_hash])
            self._witness_cache[path] = (
                _b64(cbor_self_describing(tree_to_cbor_obj(witness))),
                _b64(cbor_self_describing(list(exact_expr_path(path)))),
            )
        skip_witness = prune_for_path(self._tree, self._skip_labels())
        self._witness_cache[None] = (
            _b64(cbor_self_describing(tree_to_cbor_obj(skip_witness))),
            _b64(cbor_self_describing(list(WILDCARD_EXPR_PATH))),
        )
        return self._root

    def _skip_labels(self):
        labels = [seg.encode("utf-8") for seg in WILDCARD_EXPR_PATH]
        labels.append(self.skip_expr_hash)
        return labels

    def _certified_header_pairs(self, response):
        pairs = []
        for name, value in response.headers:
            if name.lower() in self.certified_headers:
                pairs.append((name.lower(), value))
        return pairs

    def _response_hash(self, response):
        return response_hash(
            response.status,
            self._certified_header_pairs(response),
            response.body,
            self.expr,
        )

    # -- serving ------------------------------------------------------------

    def certificate_headers(self, path, certificate):
        """Headers for a CERTIFIED route response. certificate: blob or None."""
        if self._tree is None:
            self.rebuild()
        tree_b64, expr_path_b64 = self._witness_cache[path]
        return self._headers(self.expr, tree_b64, expr_path_b64, certificate)

    def skip_headers(self, certificate):
        """Headers for an UNCERTIFIED route served via the skip wildcard."""
        if self._tree is None:
            self.rebuild()
        tree_b64, expr_path_b64 = self._witness_cache[None]
        return self._headers(SKIP_CERTIFICATION_EXPR, tree_b64, expr_path_b64, certificate)

    def _headers(self, expr, tree_b64, expr_path_b64, certificate):
        if certificate is None:
            # dev mode / no replica certificate available: expression header
            # only (documents intent; gateways aren't in play here anyway)
            return [("ic-certificateexpression", expr)]
        value = "certificate=:%s:, tree=:%s:, expr_path=:%s:, version=2" % (
            _b64(certificate),
            tree_b64,
            expr_path_b64,
        )
        return [
            ("ic-certificateexpression", expr),
            ("ic-certificate", value),
        ]


# ---------------------------------------------------------------------------
# Kybra seam (lazy imports; no-ops on host CPython)
# ---------------------------------------------------------------------------


def set_certified_data(root):
    try:
        from kybra import ic
        ic.set_certified_data(root)
        return True
    except Exception:
        return False


def data_certificate():
    try:
        from kybra import ic
        return ic.data_certificate()
    except Exception:
        return None
