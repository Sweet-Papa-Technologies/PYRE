"""pyre.time (pyre/ptime.py): consensus-safe timestamps from ic.time()."""

import sys
import time as host_time
import types

import pytest

from pyre import ptime

# A fixed ic.time() value: 2023-11-14T22:13:20.123456789 UTC.
FIXED_NS = 1_700_000_000_123_456_789


@pytest.fixture
def canister_clock(monkeypatch):
    """Pretend we're in a canister with a mocked ic.time()."""
    fake_kybra = types.ModuleType("kybra")
    fake_kybra.ic = types.SimpleNamespace(time=lambda: FIXED_NS)
    monkeypatch.setitem(sys.modules, "kybra", fake_kybra)
    monkeypatch.setattr(ptime, "in_canister", lambda: True)
    return fake_kybra


def test_now_ns_is_ic_time(canister_clock):
    assert ptime.now_ns() == FIXED_NS


def test_now_and_now_ms_derive_from_ic_time(canister_clock):
    assert ptime.now() == 1_700_000_000
    assert ptime.now_ms() == 1_700_000_000_123


def test_isoformat_from_ic_time(canister_clock):
    assert ptime.isoformat() == "2023-11-14T22:13:20.123456Z"


def test_all_functions_share_one_source(canister_clock):
    # Everything is derived from the same ic.time() read, so the values
    # must be mutually consistent at every precision.
    ns = ptime.now_ns()
    assert ptime.now_ms() == ns // 1_000_000
    assert ptime.now() == ns // 1_000_000_000


def test_dev_fallback_uses_host_clock():
    # No kybra, in_canister() False: host clock, same API.
    before = host_time.time()
    seconds = ptime.now()
    after = host_time.time()
    assert int(before) - 1 <= seconds <= int(after) + 1


def test_dev_fallback_scales_agree():
    ns = ptime.now_ns()
    ms = ptime.now_ms()
    s = ptime.now()
    assert abs(ns // 1_000_000 - ms) < 2_000  # within 2s of each other
    assert abs(ms // 1_000 - s) < 2


def test_dev_fallback_isoformat_shape():
    iso = ptime.isoformat()
    assert iso.endswith("Z")
    assert iso[4] == "-" and iso[7] == "-" and iso[10] == "T"


def test_alias_from_pyre():
    from pyre import time as aliased

    assert aliased is ptime


def test_import_pyre_time_statement_form_fails():
    # Documented caveat: there is no pyre/time.py file (it would shadow the
    # stdlib inside the Kybra bundle), so the statement form must fail.
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pyre.time")
