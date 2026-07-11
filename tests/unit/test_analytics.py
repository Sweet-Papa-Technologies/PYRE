import json

import pytest

from pyre.analytics import AnalyticsLimitError, Limits, Table, col


def sample(limits=None):
    return Table.from_records([
        {"symbol": "B", "price": 3, "size": 2},
        {"symbol": "A", "price": 2, "size": 5},
        {"symbol": "A", "price": None, "size": 1},
        {"symbol": "A", "price": -1, "size": 4},
    ], limits)


def test_documented_pipeline_is_deterministic_and_immutable():
    original = sample()
    summary = (original.filter(col("price") > 0)
               .group_by("symbol")
               .aggregate(avg_price=("price", "mean"), volume=("size", "sum"))
               .sort_by("symbol"))
    assert summary.to_records() == [
        {"avg_price": 2.0, "symbol": "A", "volume": 5},
        {"avg_price": 3.0, "symbol": "B", "volume": 2},
    ]
    assert len(original) == 4
    assert json.loads(summary.to_json()) == summary.to_records()


def test_columns_select_rename_and_null_aggregate_semantics():
    table = Table.from_columns({"b": [1, 2], "a": [None, 4]})
    assert table.columns == ("a", "b")
    assert table.select("b").rename(b="value").to_records() == [{"value": 1}, {"value": 2}]
    result = sample().group_by("symbol").aggregate(count=("price", "count"), total=("price", "sum"))
    assert result.sort_by("symbol").to_records()[0]["count"] == 3
    assert result.sort_by("symbol").to_records()[0]["total"] == 1


def test_inner_left_join_are_stable_and_bounded():
    left = Table.from_records([{"id": 1, "x": "a"}, {"id": 2, "x": "b"}])
    right = Table.from_records([{"id": 1, "x": "r1"}, {"id": 1, "x": "r2"}])
    assert left.join(right, on="id").to_records() == [
        {"id": 1, "x": "a", "x_right": "r1"},
        {"id": 1, "x": "a", "x_right": "r2"},
    ]
    assert left.join(right, on="id", how="left").to_records()[-1]["x_right"] is None
    tiny = Table.from_records(left.to_records(), Limits(join_rows=1))
    with pytest.raises(AnalyticsLimitError, match="join"):
        tiny.join(right, on="id")


def test_pivot_rolling_batches_and_cardinality_limits():
    table = Table.from_records([
        {"day": 1, "symbol": "A", "value": 2},
        {"day": 1, "symbol": "B", "value": 3},
        {"day": 2, "symbol": "A", "value": 4},
    ])
    assert table.pivot(index="day", columns="symbol", values="value").to_records() == [
        {"A": 2, "B": 3, "day": 1}, {"A": 4, "B": None, "day": 2}
    ]
    assert table.rolling("value", window=2, operation="mean").to_records()[-1]["value_mean_2"] == 3.5
    assert [len(batch) for batch in table.record_batches(2)] == [2, 1]
    with pytest.raises(AnalyticsLimitError, match="row"):
        Table.from_records([{"x": 1}, {"x": 2}], Limits(rows=1))
    with pytest.raises(AnalyticsLimitError, match="group"):
        sample(Limits(groups=1)).group_by("symbol").aggregate(n=("size", "count"))
    with pytest.raises(ValueError, match="duplicate string"):
        Table.from_records([{"i": 1, "c": 1, "v": 2}, {"i": 1, "c": "1", "v": 3}]).pivot(
            index="i", columns="c", values="v")


def test_row_limit_is_enforced_while_consuming_generator():
    consumed = []
    def records():
        for index in range(100):
            consumed.append(index); yield {"x": index}
    with pytest.raises(AnalyticsLimitError, match="row"):
        Table.from_records(records(), Limits(rows=3))
    assert consumed == [0, 1, 2, 3]
