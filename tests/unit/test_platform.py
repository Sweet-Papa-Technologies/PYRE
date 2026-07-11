import pytest
import sys
import types

from pyre import _platform


class FakePlatform:
    def __init__(self):
        self.now = 123
        self.calls = []

    def now_ns(self):
        return self.now

    def set_timer(self, delay_ns, callback):
        self.calls.append((delay_ns, callback))
        return 7


def teardown_function():
    _platform.reset_adapter()


def test_host_operations_fail_with_specific_error():
    with pytest.raises(_platform.PlatformUnavailable, match="test platform adapter"):
        _platform.now_ns()


def test_fake_adapter_is_injectable():
    fake = FakePlatform()
    _platform.install_adapter(fake)
    callback = lambda: None
    assert _platform.now_ns() == 123
    assert _platform.set_timer(5, callback) == 7
    assert fake.calls == [(5, callback)]


def test_canister_adapter_delegates_to_documented_kybra_surface(monkeypatch):
    calls = []
    class Principal:
        @staticmethod
        def from_str(value): return "principal:" + value
    fake_ic = types.SimpleNamespace(
        time=lambda: 99,
        set_timer=lambda delay, callback: calls.append(("timer", delay, callback)) or 4,
        clear_timer=lambda handle: calls.append(("clear", handle)),
        call_raw=lambda *args: ("call", args), notify_raw=lambda *args: ("notify", args),
        candid_encode=lambda text: ("encoded:" + text).encode(),
        candid_decode=lambda payload: "decoded:" + payload.decode(),
    )
    monkeypatch.setitem(sys.modules, "kybra", types.SimpleNamespace(ic=fake_ic, Principal=Principal))
    adapter = _platform._CanisterAdapter()
    assert adapter.now_ns() == 99
    assert adapter.set_timer(8, lambda: None) == 4
    assert adapter.call_raw("aaaaa-aa", "go", b"x", cycles=7)[1] == ("principal:aaaaa-aa", "go", b"x", 7)
    assert adapter.notify_raw("aaaaa-aa", "go", b"x", cycles=2)[0] == "notify"
    assert adapter.candid_decode(adapter.candid_encode("(1)")) == "decoded:encoded:(1)"
