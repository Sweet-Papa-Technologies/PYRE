# Experimental bounded analytics

`pyre.analytics` is pure Python, immutable, experimental, and not pandas:

```python
from pyre.analytics import Table, col

summary = (Table.from_records(records)
    .filter(col("price") > 0)
    .group_by("symbol")
    .aggregate(avg_price=("price", "mean"), volume=("size", "sum"))
    .sort_by("symbol"))
```

Supported operations are records/columns/JSON conversion, select/rename,
filter/sort, bounded group aggregates, inner/left joins, pivots, rolling
sum/mean, and bounded record batches. Filters and selection are O(n), sorting
O(n log n), and hash grouping/join expected O(n), with additional output memory.

Default limits are 10,000 rows, 100 columns, 2,000 groups, 20,000 joined rows,
and 200 pivot columns. `None` is excluded from numeric aggregates but counted by
`count`; ordered null comparisons are false. NaN sorts after ordinary values and
JSON rejects it. Prefer integer fixed-point or `Decimal` for money.

Persist `record_batches()` explicitly rather than one unbounded KV value.
Schema compatibility is controlled by the application. Host timings in
`DECISIONS.md` are not canister instruction claims; Wasm measurement remains a
release gate.

