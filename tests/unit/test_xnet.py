import asyncio

import pytest

from pyre._runtime import ctx
from pyre.candid import CandidDecodeError, MethodSpec, ServiceSpec, TypeSpec
from pyre.xnet import (
    CanisterClient, PayloadTooLarge, QueryContextCallError, UnknownMethod,
    _candid_text, _decode_candid_text, _text_literal, _unescape_text,
)


class FakeTransport:
    def __init__(self, reply=b"reply"):
        self.reply = reply
        self.calls = []
        self.notifications = []

    def encode(self, method, args):
        return (method.name + ":" + repr(args)).encode()

    async def call(self, canister_id, method, payload, cycles):
        self.calls.append((canister_id, method, payload, cycles))
        return self.reply

    def decode(self, method, payload):
        return {"method": method.name, "reply": payload.decode()}

    def notify(self, canister_id, method, payload, cycles):
        self.notifications.append((canister_id, method, payload, cycles))
        return True


def client(transport=None, maximum=1_900_000):
    service = ServiceSpec([
        MethodSpec("get", (), (TypeSpec("nat"),), mode="query"),
        MethodSpec("set", (TypeSpec("nat8"),), ()),
    ], name="Counter")
    return CanisterClient("aaaaa-aa", service, default_cycles=7,
                          max_payload_bytes=maximum, transport=transport or FakeTransport())


def teardown_function():
    ctx.in_query = False


def test_success_explicit_cycles_notify_and_unknown_method():
    transport = FakeTransport()
    target = client(transport)
    assert asyncio.run(target.call("set", 3, cycles=9))["reply"] == "reply"
    assert transport.calls[0][3] == 9
    assert target.notify("get") is True
    assert transport.notifications[0][3] == 7
    with pytest.raises(UnknownMethod):
        asyncio.run(target.call("missing"))


def test_query_context_and_request_reply_size_guards():
    ctx.in_query = True
    with pytest.raises(QueryContextCallError):
        asyncio.run(client().call("get"))
    ctx.in_query = False
    with pytest.raises(PayloadTooLarge) as request_error:
        asyncio.run(client(maximum=3).call("get"))
    assert request_error.value.actual > request_error.value.allowed
    with pytest.raises(PayloadTooLarge):
        asyncio.run(client(FakeTransport(reply=b"12345"), maximum=4).call("get"))


def test_decode_failure_names_method():
    transport = FakeTransport()
    transport.decode = lambda method, payload: (_ for _ in ()).throw(ValueError("bad wire"))
    with pytest.raises(CandidDecodeError, match="get response"):
        asyncio.run(client(transport).call("get"))


def test_argument_bounds_checked_before_transport():
    transport = FakeTransport()
    with pytest.raises(Exception, match="nat8 bounds"):
        asyncio.run(client(transport).call("set", 999))
    assert transport.calls == []


def test_principal_checksum_is_validated_before_encoding():
    with pytest.raises(ValueError, match="invalid canister principal"):
        CanisterClient("aaaaa-ab", ServiceSpec([MethodSpec("get")]))


def test_runtime_candid_text_is_deterministic_for_nested_values():
    spec = TypeSpec.record({
        "owner": TypeSpec("principal"),
        "amounts": TypeSpec.vec(TypeSpec("nat64")),
        "memo": TypeSpec.opt(TypeSpec("text")),
    })
    assert _candid_text(spec, {
        "owner": "aaaaa-aa", "amounts": [1, 2], "memo": None,
    }) == 'record { amounts = vec { 1; 2 }; memo = null; owner = principal "aaaaa-aa" }'


def test_runtime_decode_validates_nested_response_text():
    spec = TypeSpec.record({
        "owner": TypeSpec("principal"),
        "result": TypeSpec.variant({"ok": TypeSpec("nat64"), "err": TypeSpec("text")}),
        "tags": TypeSpec.vec(TypeSpec("text")),
    })
    decoded = _decode_candid_text(
        '(record { owner = principal "aaaaa-aa"; result = variant { ok = 7 }; tags = vec { "a"; "b" } })',
        (spec,),
    )
    assert decoded == ({"owner": "aaaaa-aa", "result": {"ok": 7}, "tags": ["a", "b"]},)
    with pytest.raises(CandidDecodeError, match="unknown record field"):
        _decode_candid_text('(record { surprise = 1 })', (spec,))


def test_runtime_decode_handles_annotations_blob_and_arity():
    assert _decode_candid_text('(42 : nat64, blob "\\00\\ff")',
                               (TypeSpec("nat64"), TypeSpec("blob"))) == (42, b"\x00\xff")
    with pytest.raises(CandidDecodeError, match="too many"):
        _decode_candid_text('(1, 2)', (TypeSpec("nat"),))


def test_text_codec_round_trips_unicode_and_uses_candid_escapes():
    # regression: json.dumps(ensure_ascii=True) emitted invalid \uXXXX; Candid
    # needs \u{...}. Encoder must round-trip through the decoder for any str.
    for original in ["café ☃", 'q"u\\o\ttes', "日本語 🚀", "plain", ""]:
        assert _unescape_text(_text_literal(original)) == original
    assert "\\u{e9}" in _text_literal("é")
    assert "\\u00e9" not in _text_literal("é")


def test_decode_accepts_replica_byte_and_scalar_escapes():
    text = (TypeSpec("text"),)
    # replica encodes non-ASCII as \XX UTF-8 byte escapes or \u{...} scalars
    assert _decode_candid_text(r'("caf\c3\a9")', text) == ("café",)
    assert _decode_candid_text(r'("\u{2603}")', text) == ("☃",)
    with pytest.raises(CandidDecodeError):
        _decode_candid_text(r'("\zz")', text)


def test_numeric_literals_accept_underscore_digit_groups():
    assert _decode_candid_text("(1_000_000 : nat)", (TypeSpec("nat"),)) == (1_000_000,)
    assert _decode_candid_text("(1_000.5 : float64)", (TypeSpec("float64"),)) == (1000.5,)
