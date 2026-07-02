import pytest

from pyre import kv
from pyre._runtime import ctx
from pyre.errors import KvWriteInQueryContext


@pytest.fixture(autouse=True)
def clean_store():
    ctx.in_query = False
    for key in list(kv.keys()):
        kv.delete(key)
    yield
    ctx.in_query = False


def test_set_get_roundtrip():
    kv.set("item:1", {"id": 1, "name": "flame"})
    assert kv.get("item:1") == {"id": 1, "name": "flame"}


def test_get_missing_returns_default():
    assert kv.get("nope") is None
    assert kv.get("nope", default=42) == 42


def test_delete():
    kv.set("k", "v")
    assert kv.delete("k") is True
    assert kv.delete("k") is False
    assert kv.get("k") is None


def test_keys():
    kv.set("a", 1)
    kv.set("b", 2)
    assert sorted(kv.keys()) == ["a", "b"]


def test_write_in_query_context_raises():
    ctx.in_query = True
    with pytest.raises(KvWriteInQueryContext):
        kv.set("k", "v")
    with pytest.raises(KvWriteInQueryContext):
        kv.delete("k")


def test_read_in_query_context_allowed():
    kv.set("k", "v")
    ctx.in_query = True
    assert kv.get("k") == "v"


def test_oversized_key_rejected():
    with pytest.raises(ValueError):
        kv.set("x" * 2000, "v")
