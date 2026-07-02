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
