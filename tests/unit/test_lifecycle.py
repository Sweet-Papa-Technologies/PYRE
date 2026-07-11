import pytest

from pyre import _lifecycle


class App:
    def __init__(self, calls):
        self.calls = calls

    def recertify(self):
        self.calls.append("recertify")


def setup_function():
    _lifecycle.clear_hooks()


def teardown_function():
    _lifecycle.clear_hooks()


def test_recertifies_then_runs_hooks_in_order_and_name_order():
    calls = []
    _lifecycle.register("z", lambda: calls.append("z"), order=2)
    _lifecycle.register("b", lambda: calls.append("b"), order=1)
    _lifecycle.register("a", lambda: calls.append("a"), order=1)
    _lifecycle.run_init(App(calls))
    assert calls == ["recertify", "a", "b", "z"]


def test_duplicate_and_required_failure_behavior():
    _lifecycle.register("same", lambda: None)
    with pytest.raises(_lifecycle.LifecycleError):
        _lifecycle.register("same", lambda: None)

    _lifecycle.clear_hooks()
    _lifecycle.register("optional", lambda: (_ for _ in ()).throw(ValueError("no")), required=False)
    _lifecycle.register("required", lambda: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError, match="stop"):
        _lifecycle.run_post_upgrade(App([]))


def test_hook_names_are_bounded_and_log_safe():
    with pytest.raises(ValueError, match="1-128"):
        _lifecycle.register("x" * 129, lambda: None)
    with pytest.raises(ValueError, match="printable"):
        _lifecycle.register("bad\nname", lambda: None)
