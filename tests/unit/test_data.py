"""WS-B: the pyre.data collections layer."""

import pytest

from pyre import data, kv
from pyre._runtime import ctx
from pyre.validation import ValidationError


@pytest.fixture(autouse=True)
def clean_store():
    ctx.in_query = False
    for key in list(kv.keys()):
        kv.delete(key)
    yield
    ctx.in_query = False


FOOD_SCHEMA = {"name": str, "kcal": int, "note": (str, "")}


def make_foods(**kwargs):
    return data.collection("foods", schema=FOOD_SCHEMA, **kwargs)


def test_insert_get_roundtrip_with_id():
    foods = make_foods()
    created = foods.insert({"name": "apple", "kcal": 52})
    assert created["id"]
    assert created["note"] == ""  # schema default applied
    fetched = foods.get(created["id"])
    assert fetched == created


def test_insert_validates_schema():
    foods = make_foods()
    with pytest.raises(ValidationError):
        foods.insert({"name": "apple"})  # kcal missing


def test_update_merges_and_replace_requires_existing():
    foods = make_foods()
    item = foods.insert({"name": "apple", "kcal": 52})
    updated = foods.update(item["id"], {"kcal": 95})
    assert updated["kcal"] == 95
    assert updated["name"] == "apple"
    with pytest.raises(KeyError):
        foods.replace("000000009999", {"name": "x", "kcal": 1})


def test_delete():
    foods = make_foods()
    item = foods.insert({"name": "apple", "kcal": 52})
    assert foods.delete(item["id"]) is True
    assert foods.delete(item["id"]) is False
    assert foods.get(item["id"]) is None


def test_list_pagination_insertion_ordered():
    foods = make_foods()
    for i in range(5):
        foods.insert({"name": "food%d" % i, "kcal": i})
    page1 = foods.list(limit=2)
    assert [d["name"] for d in page1["items"]] == ["food0", "food1"]
    assert page1["next"] is not None
    page2 = foods.list(limit=2, after=page1["next"])
    assert [d["name"] for d in page2["items"]] == ["food2", "food3"]
    page3 = foods.list(limit=2, after=page2["next"])
    assert [d["name"] for d in page3["items"]] == ["food4"]
    assert page3["next"] is None


def test_list_where_filter():
    foods = make_foods()
    foods.insert({"name": "apple", "kcal": 52})
    foods.insert({"name": "banana", "kcal": 89})
    foods.insert({"name": "apple", "kcal": 95})
    result = foods.list(where={"name": "apple"})
    assert len(result["items"]) == 2
    assert all(d["name"] == "apple" for d in result["items"])


def test_count_and_isolation_between_collections():
    foods = make_foods()
    drinks = data.collection("drinks")
    foods.insert({"name": "apple", "kcal": 52})
    drinks.insert({"kind": "tea"})
    assert foods.count() == 1
    assert drinks.count() == 1
    assert drinks.list()["items"][0]["kind"] == "tea"


def test_lazy_migration_gains_field_without_data_loss():
    # v1 writes...
    foods_v1 = make_foods()
    item = foods_v1.insert({"name": "apple", "kcal": 52})

    # ...then the app upgrades to v2 with a new required list field
    schema_v2 = {"name": str, "kcal": int, "note": (str, ""), "tags": [str]}
    foods_v2 = data.collection(
        "foods",
        schema=schema_v2,
        version=2,
        migrate=lambda doc, v: dict(doc, tags=[]),
    )
    migrated = foods_v2.get(item["id"])
    assert migrated["tags"] == []
    assert migrated["name"] == "apple"  # nothing lost

    # writing persists the migrated shape at the new version
    foods_v2.update(item["id"], {"tags": ["fruit"]})
    raw = kv.get("c:foods:%s" % item["id"])
    assert raw["_v"] == 2
    assert raw["tags"] == ["fruit"]


def test_version_bump_requires_migrate():
    with pytest.raises(ValueError):
        data.collection("x", version=2)


def test_list_bounds_scan_and_returns_resume_cursor():
    # A where-filter that matches nothing must not scan the whole (large)
    # collection in one call: the scan is bounded to max_scan and hands back
    # a cursor so the caller resumes, instead of doing unbounded per-message
    # work (the DoS guard, see data.MAX_SCAN).
    foods = make_foods()
    for i in range(25):
        foods.insert({"name": "n%02d" % i, "kcal": i})

    page = foods.list(where={"name": "does-not-exist"}, max_scan=10)
    assert page["items"] == []
    assert page["next"] is not None  # budget hit before finishing → resume cursor

    # Walking the cursor eventually drains the collection (next → None).
    cursor, seen, guard = page["next"], 0, 0
    while cursor is not None and guard < 100:
        nxt = foods.list(where={"name": "does-not-exist"}, after=cursor, max_scan=10)
        assert nxt["items"] == []
        seen += 1
        cursor = nxt["next"]
        guard += 1
    assert cursor is None  # fully scanned, no infinite loop


def test_list_small_collection_completes_without_cursor():
    foods = make_foods()
    for i in range(3):
        foods.insert({"name": "n%d" % i, "kcal": i})
    page = foods.list()
    assert len(page["items"]) == 3
    assert page["next"] is None
