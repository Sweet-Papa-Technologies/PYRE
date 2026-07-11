import pytest

from pyre import kv
from pyre._namespace import delete_prefix, framework_key, list_prefix


def setup_function():
    kv._backend = kv._DevBackend()
    kv.ctx.in_query = False


def test_key_is_versioned_and_components_are_unambiguous():
    assert framework_key("tasks", 1, "record", "a:b") == "__pyre:tasks:1:record:a%3Ab"


def test_validation_and_prefix_operations_do_not_touch_application_keys():
    with pytest.raises(ValueError):
        framework_key("tasks", 0, "record")
    with pytest.raises(ValueError):
        framework_key("tasks", 1, "record", "bad\nname")
    kv.set("application", 1)
    key = framework_key("tasks", 1, "record", "job")
    kv.set(key, {"schema": 1})
    assert list_prefix("tasks", 1) == [key]
    assert delete_prefix("tasks", 1) == 1
    assert kv.get("application") == 1


def test_prefix_length_is_bounded_before_scanning():
    with pytest.raises(ValueError, match="prefix exceeds"):
        list_prefix("x" * 2000, 1)
