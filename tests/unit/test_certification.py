import hashlib
import json

from pyre import App, Response
from pyre.certification import (
    SKIP_CERTIFICATION_EXPR,
    CertifiedStore,
    cbor_encode,
    cbor_self_describing,
    exact_expr_path,
    from_labeled_children,
    hash_of_map,
    leb128_u,
    prune_for_path,
    response_hash,
    response_only_expr,
    tree_from_paths,
    tree_hash,
    tree_to_cbor_obj,
)


def sha(data):
    return hashlib.sha256(data).digest()


# --- primitives --------------------------------------------------------------


def test_leb128():
    assert leb128_u(0) == b"\x00"
    assert leb128_u(127) == b"\x7f"
    assert leb128_u(128) == b"\x80\x01"
    assert leb128_u(300) == b"\xac\x02"  # canonical LEB128 example
    assert leb128_u(624485) == b"\xe5\x8e\x26"  # wikipedia test vector


def test_hash_of_map_is_order_independent_and_matches_manual():
    entries_a = [("a", "x"), ("b", 7)]
    entries_b = [("b", 7), ("a", "x")]
    assert hash_of_map(entries_a) == hash_of_map(entries_b)
    manual = sorted([sha(b"a") + sha(b"x"), sha(b"b") + sha(leb128_u(7))])
    assert hash_of_map(entries_a) == sha(b"".join(manual))


def test_response_hash_includes_expr_and_status_pseudo_header():
    expr = response_only_expr(("content-type",))
    body = b'{"status": "ok"}'
    got = response_hash(200, [("content-type", "application/json")], body, expr)
    entries = [
        ("content-type", "application/json"),
        ("ic-certificateexpression", expr),
        (":ic-cert-status", 200),
    ]
    assert got == sha(hash_of_map(entries) + sha(body))
    # status participates: different status → different hash
    assert got != response_hash(201, [("content-type", "application/json")], body, expr)


# --- hash tree ----------------------------------------------------------------


def test_tree_hash_domain_separation():
    leaf = ("leaf", b"hello")
    assert tree_hash(leaf) == sha(b"\x10ic-hashtree-leaf" + b"hello")
    labeled = ("labeled", b"lbl", leaf)
    assert tree_hash(labeled) == sha(b"\x13ic-hashtree-labeled" + b"lbl" + tree_hash(leaf))
    fork = ("fork", labeled, ("empty",))
    empty_hash = sha(b"\x11ic-hashtree-empty")
    assert tree_hash(fork) == sha(b"\x10ic-hashtree-fork" + tree_hash(labeled) + empty_hash)


def test_pruned_preserves_root_hash():
    tree = tree_from_paths(
        [
            ([b"a", b"x"], b"1"),
            ([b"b", b"y"], b"2"),
            ([b"c", b"z"], b"3"),
        ]
    )
    witness = prune_for_path(tree, [b"b", b"y"])
    assert tree_hash(witness) == tree_hash(tree)

    def has_leaf(node, data):
        if node[0] == "leaf":
            return node[1] == data
        if node[0] in ("fork",):
            return has_leaf(node[1], data) or has_leaf(node[2], data)
        if node[0] == "labeled":
            return has_leaf(node[2], data)
        return False

    assert has_leaf(witness, b"2")  # path data revealed
    assert not has_leaf(witness, b"1")  # siblings pruned
    assert not has_leaf(witness, b"3")


def test_children_sorted_by_label():
    tree = from_labeled_children([(b"b", ("leaf", b"2")), (b"a", ("leaf", b"1"))])
    # fork(left=labeled a, right=labeled b)
    assert tree[0] == "fork"
    assert tree[1][1] == b"a"
    assert tree[2][1] == b"b"


# --- CBOR ---------------------------------------------------------------------


def test_cbor_encoding_primitives():
    assert cbor_encode(0) == b"\x00"
    assert cbor_encode(23) == b"\x17"
    assert cbor_encode(24) == b"\x18\x18"
    assert cbor_encode(b"\x01\x02") == b"\x42\x01\x02"
    assert cbor_encode("hi") == b"\x62hi"
    assert cbor_encode([0]) == b"\x81\x00"
    assert cbor_self_describing([0]).startswith(b"\xd9\xd9\xf7")  # tag 55799


def test_tree_cbor_shape():
    node = ("fork", ("labeled", b"a", ("leaf", b"x")), ("pruned", b"\x00" * 32))
    obj = tree_to_cbor_obj(node)
    assert obj == [1, [2, b"a", [3, b"x"]], [4, b"\x00" * 32]]


# --- expressions & paths --------------------------------------------------------


def test_cel_expressions_match_spec_ebnf():
    assert SKIP_CERTIFICATION_EXPR == (
        "default_certification(ValidationArgs{no_certification:Empty{}})"
    )
    expr = response_only_expr(("content-type",))
    assert expr == (
        "default_certification(ValidationArgs{certification:Certification{"
        "no_request_certification:Empty{},response_certification:"
        'ResponseCertification{certified_response_headers:ResponseHeaderList{'
        'headers:["content-type"]}}}})'
    )
    assert " " not in expr  # EBNF forbids whitespace


def test_expr_paths():
    assert exact_expr_path("/health") == ["http_expr", "health", "<$>"]
    assert exact_expr_path("/a/b") == ["http_expr", "a", "b", "<$>"]
    assert exact_expr_path("/") == ["http_expr", "", "<$>"]


# --- store end-to-end -----------------------------------------------------------


def make_store():
    store = CertifiedStore()
    store.put("/health", Response.json({"status": "ok"}))
    store.rebuild()
    return store


def test_store_tree_contains_expected_leaf():
    store = make_store()
    resp = store.responses["/health"]
    expected_leaf_path = [
        b"http_expr",
        b"health",
        b"<$>",
        store.expr_hash,
        b"",
        store._response_hash(resp),
    ]
    node = store._tree

    def lookup(node, labels):
        if not labels:
            return node
        if node[0] == "fork":
            return lookup(node[1], labels) or lookup(node[2], labels)
        if node[0] == "labeled" and node[1] == labels[0]:
            return lookup(node[2], labels[1:])
        return None

    found = lookup(node, expected_leaf_path)
    assert found == ("leaf", b"")
    # skip wildcard present too
    assert lookup(node, [b"http_expr", b"<*>", store.skip_expr_hash]) == ("leaf", b"")


def test_certificate_headers_dev_mode_expression_only():
    store = make_store()
    headers = store.certificate_headers("/health", None)
    assert headers == [("ic-certificateexpression", store.expr)]


def test_certificate_headers_with_certificate():
    store = make_store()
    headers = dict(store.certificate_headers("/health", b"\x01\x02"))
    value = headers["ic-certificate"]
    assert "certificate=:" in value and "tree=:" in value
    assert "version=2" in value and "expr_path=:" in value


def test_official_response_hash_vector():
    # dfinity/response-verification response_hash_with_certified_headers
    expr = (
        "default_certification(ValidationArgs{certification:Certification{"
        "no_request_certification:Empty{},response_certification:ResponseCertification{"
        'certified_response_headers:ResponseHeaderList{headers:["Accept-Encoding","Cache-Control"]}}}})'
    )
    got = response_hash(
        200,
        [("accept-encoding", "gzip"), ("cache-control", "no-cache"), ("cache-control", "no-store")],
        b"Hello World!",
        expr,
    )
    assert got.hex() == "3393250e3cedc30408dcb7e8963898c3d7549b8a0b76496b82fdfeae99c2ac78"


def test_witness_reveals_leaf_below_expr_hash():
    # regression: the gateway must find ["", response_hash] -> leaf "" UNDER
    # expr_hash; pruning below the path endpoint broke verification on-chain
    store = make_store()
    resp = store.responses["/health"]
    labels = [b"http_expr", b"health", b"<$>", store.expr_hash]
    witness = prune_for_path(store._tree, labels)

    def lookup(node, path):
        if not path:
            return node
        if node[0] == "fork":
            return lookup(node[1], path) or lookup(node[2], path)
        if node[0] == "labeled" and node[1] == path[0]:
            return lookup(node[2], path[1:])
        return None

    leaf = lookup(witness, labels + [b"", store._response_hash(resp)])
    assert leaf == ("leaf", b"")


def test_witness_root_matches_committed_root():
    store = make_store()
    root = store.rebuild()
    labels = [b"http_expr", b"health", b"<$>", store.expr_hash]
    witness = prune_for_path(store._tree, labels)
    assert tree_hash(witness) == root
    skip_witness = prune_for_path(store._tree, [b"http_expr", b"<*>", store.skip_expr_hash])
    assert tree_hash(skip_witness) == root


# --- App integration --------------------------------------------------------------


def test_app_recertify_and_serve_snapshot():
    app = App()
    state = {"n": 1}

    @app.get("/count", certified=True)
    def count(req):
        return Response.json({"n": state["n"]})

    app.recertify()
    assert "/count" in app.certification.responses

    from pyre.http_types import Request

    served = app.handle_query(Request("GET", "/count"))
    assert json.loads(served.body.decode()) == {"n": 1}

    # live state changes don't leak into certified reads until recertify
    state["n"] = 2
    served = app.handle_query(Request("GET", "/count"))
    assert json.loads(served.body.decode()) == {"n": 1}
    app.recertify()
    served = app.handle_query(Request("GET", "/count"))
    assert json.loads(served.body.decode()) == {"n": 2}


def test_certified_route_validation():
    app = App()
    import pytest

    with pytest.raises(ValueError):
        @app.get("/items/{id}", certified=True)
        def bad(req):
            return Response.text("x")

    with pytest.raises(ValueError):
        @app.get("/w", certified=True, update=True)
        def bad2(req):
            return Response.text("x")


def test_recertify_rejects_non_2xx():
    app = App()

    @app.get("/broken", certified=True)
    def broken(req):
        return Response.json({"error": "nope"}, status=404)

    import pytest
    from pyre.errors import PyreError

    with pytest.raises(PyreError):
        app.recertify()
