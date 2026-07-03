"""pyre.random (pyre/prandom.py): two-tier consensus-safe randomness."""

import re
import sys
import types

import pytest

from pyre import App, Response, prandom, ptime
from pyre._runtime import ctx
from pyre.errors import PyreError
from pyre.http_types import Request
from pyre.outcall import pump, pump_sync

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

T1 = 1_700_000_000_000_000_000
T2 = 1_700_000_001_000_000_000


def fresh_replica(t=T1):
    """A fresh 'replica': clean DRBG state, deterministic message time."""
    return prandom._Drbg(time_ns=lambda: t, entropy=b"")


# -- tier 1: determinism (the consensus property) --------------------------------


def test_two_replicas_produce_identical_streams():
    a, b = fresh_replica(), fresh_replica()
    assert [a.take(16) for _ in range(20)] == [b.take(16) for _ in range(20)]


def test_different_message_time_gives_different_values():
    assert fresh_replica(T1).take(32) != fresh_replica(T2).take(32)


def test_module_functions_are_deterministic_across_replicas(monkeypatch):
    def draw_everything():
        monkeypatch.setattr(prandom, "_drbg", fresh_replica())
        return (
            [prandom.random() for _ in range(5)],
            [prandom.randint(0, 1000) for _ in range(5)],
            prandom.weak_token_hex(16),
            [prandom.uuid4() for _ in range(5)],
            prandom.choice(["a", "b", "c", "d"]),
        )

    assert draw_everything() == draw_everything()


def test_counter_advances_within_a_message():
    # Same ic.time() for every draw (one message): values must still differ.
    replica = fresh_replica()
    assert replica.take(32) != replica.take(32)


def test_mixing_entropy_changes_the_stream():
    plain, mixed = fresh_replica(), fresh_replica()
    mixed.mix(b"raw_rand entropy")
    assert plain.take(32) != mixed.take(32)


# -- tier 1: value contracts ------------------------------------------------------


@pytest.fixture
def seeded(monkeypatch):
    monkeypatch.setattr(prandom, "_drbg", fresh_replica())


def test_random_range_and_variety(seeded):
    values = [prandom.random() for _ in range(200)]
    assert all(0.0 <= v < 1.0 for v in values)
    assert len(set(values)) > 190  # not a constant


def test_randint_inclusive_bounds(seeded):
    values = [prandom.randint(1, 6) for _ in range(600)]
    assert set(values) == {1, 2, 3, 4, 5, 6}


def test_randint_distribution_sanity(seeded):
    counts = {i: 0 for i in range(4)}
    for _ in range(2000):
        counts[prandom.randint(0, 3)] += 1
    for count in counts.values():  # ~500 expected; loose sanity bound
        assert 350 < count < 650


def test_randint_degenerate_and_invalid(seeded):
    assert prandom.randint(7, 7) == 7
    with pytest.raises(ValueError):
        prandom.randint(3, 2)


def test_choice(seeded):
    seq = ["red", "green", "blue"]
    assert all(prandom.choice(seq) in seq for _ in range(50))
    with pytest.raises(IndexError):
        prandom.choice([])


def test_weak_token_hex_length_and_charset(seeded):
    token = prandom.weak_token_hex(8)
    assert len(token) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", token)
    assert len(prandom.weak_token_hex()) == 32  # default n=16
    # correlation_id is an alias with the same contract
    assert len(prandom.correlation_id(8)) == 16


def test_uuid4_format_and_uniqueness_in_one_message(seeded):
    uuids = [prandom.uuid4() for _ in range(100)]
    assert all(UUID4_RE.match(u) for u in uuids)
    assert len(set(uuids)) == 100


def test_uuid4_version_and_variant_bits_forced():
    # All-zero input bytes: only the forced version/variant bits survive.
    assert prandom._format_uuid4(b"\x00" * 16) == "00000000-0000-4000-8000-000000000000"


# -- tier 2: raw_bytes over the pump ----------------------------------------------


def rand_resolver(byte=0xAB):
    calls = []

    def resolve(fut):
        assert isinstance(fut, prandom.RawRandFuture)
        calls.append(fut)
        return bytes([byte + len(calls) - 1]) * 32

    return resolve, calls


def test_raw_bytes_dev_fallback_needs_no_resolver():
    def no_resolver(fut):  # pragma: no cover
        raise AssertionError("dev-mode raw_bytes must not yield")

    out = pump_sync(prandom.raw_bytes(48), no_resolver)
    assert isinstance(out, bytes) and len(out) == 48


def test_raw_bytes_single_call_for_32(monkeypatch):
    monkeypatch.setattr(prandom, "in_canister", lambda: True)
    resolve, calls = rand_resolver()
    out = pump_sync(prandom.raw_bytes(32), resolve)
    assert out == b"\xab" * 32
    assert len(calls) == 1


def test_raw_bytes_concatenates_beyond_32(monkeypatch):
    monkeypatch.setattr(prandom, "in_canister", lambda: True)
    resolve, calls = rand_resolver()
    out = pump_sync(prandom.raw_bytes(40), resolve)
    assert len(calls) == 2  # two raw_rand round trips
    assert out == b"\xab" * 32 + b"\xac" * 8


def test_raw_bytes_edge_sizes(monkeypatch):
    monkeypatch.setattr(prandom, "in_canister", lambda: True)
    resolve, calls = rand_resolver()
    assert pump_sync(prandom.raw_bytes(0), resolve) == b""
    assert len(pump_sync(prandom.raw_bytes(1), resolve)) == 1
    with pytest.raises(ValueError):
        pump_sync(prandom.raw_bytes(-1), resolve)


def test_raw_bytes_in_query_context_raises():
    ctx.in_query = True
    try:
        with pytest.raises(prandom.RawRandInQueryContext):
            pump_sync(prandom.raw_bytes(), lambda fut: b"\x00" * 32)
    finally:
        ctx.in_query = False


def test_uuid4_strong_from_raw_rand(monkeypatch):
    monkeypatch.setattr(prandom, "in_canister", lambda: True)
    uid = pump_sync(prandom.uuid4_strong(), lambda fut: b"\x00" * 32)
    assert uid == "00000000-0000-4000-8000-000000000000"


def test_reseed_mixes_raw_rand_into_drbg(monkeypatch):
    monkeypatch.setattr(prandom, "in_canister", lambda: True)
    monkeypatch.setattr(prandom, "_drbg", fresh_replica())
    unmixed = fresh_replica()
    pump_sync(prandom.reseed(), lambda fut: b"\x11" * 32)
    assert prandom._drbg.take(32) != unmixed.take(32)


# -- tier 2: the real Kybra generator protocol (mocked kybra seam) -----------------

RAW_RAND_CALL = {"call": "management_canister.raw_rand"}


@pytest.fixture
def fake_kybra(monkeypatch):
    """Install kybra + kybra.canisters.management fakes into sys.modules."""
    kybra = types.ModuleType("kybra")
    kybra.ic = types.SimpleNamespace(time=lambda: T1)
    canisters = types.ModuleType("kybra.canisters")
    management = types.ModuleType("kybra.canisters.management")
    management.management_canister = types.SimpleNamespace(
        raw_rand=lambda: RAW_RAND_CALL
    )
    monkeypatch.setitem(sys.modules, "kybra", kybra)
    monkeypatch.setitem(sys.modules, "kybra.canisters", canisters)
    monkeypatch.setitem(sys.modules, "kybra.canisters.management", management)
    monkeypatch.setattr(prandom, "in_canister", lambda: True)
    monkeypatch.setattr(ptime, "in_canister", lambda: True)
    return kybra


def test_pump_yields_real_raw_rand_call(fake_kybra):
    async def handler():
        return await prandom.raw_bytes(32)

    gen = pump(handler())
    assert gen.send(None) is RAW_RAND_CALL  # exactly what Kybra would receive
    with pytest.raises(StopIteration) as stop:
        gen.send({"Ok": b"\x5a" * 32})
    assert stop.value.value == b"\x5a" * 32


def test_pump_raw_rand_err_thrown_into_handler(fake_kybra):
    async def handler():
        try:
            await prandom.raw_bytes(32)
        except PyreError as e:
            return "caught:%s" % e

    gen = pump(handler())
    gen.send(None)
    with pytest.raises(StopIteration) as stop:
        gen.send({"Err": "canister out of cycles"})
    assert stop.value.value == "caught:management canister raw_rand failed: canister out of cycles"


def test_raw_bytes_completes_through_handle_update(fake_kybra):
    app = App()

    @app.post("/token")
    async def token(req):
        raw = await prandom.raw_bytes(32)
        return Response.json({"token": raw.hex()})

    gen = app.handle_update(Request("POST", "/token"))
    assert gen.send(None) is RAW_RAND_CALL
    with pytest.raises(StopIteration) as stop:
        gen.send({"Ok": b"\xee" * 32})
    response = stop.value.value
    assert response.status == 200
    assert ("ee" * 32).encode() in response.body


# -- DX aliases --------------------------------------------------------------------


def test_pyre_random_and_uuid_aliases():
    import pyre
    from pyre import random as aliased_random
    from pyre import uuid as aliased_uuid

    assert aliased_random is prandom
    assert aliased_uuid is pyre.puuid
    assert aliased_uuid.uuid4 is prandom.uuid4
    assert aliased_uuid.uuid4_strong is prandom.uuid4_strong


def test_import_pyre_random_statement_form_fails():
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pyre.random")
