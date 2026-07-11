"""EXPERIMENTAL bounded, deterministic pure-Python tabular analytics.

This API is not pandas-compatible. Transformations are immutable and allocate
new rows. Filter/select are O(n); stable sort is O(n log n); grouping and
hash joins are expected O(n), bounded by explicit cardinality limits.
``None`` is excluded from numeric aggregates except ``count``. NaN values are
accepted but sort after ordinary values; use Decimal/fixed-point integers for
financial calculations where binary floating-point is unsuitable.
"""

import json
import math

EXPERIMENTAL = True


class AnalyticsLimitError(ValueError):
    code = "PYRE-ANALYTICS-LIMIT"


class Limits:
    def __init__(self, rows=10_000, columns=100, groups=2_000,
                 join_rows=20_000, pivot_columns=200):
        self.rows, self.columns, self.groups = int(rows), int(columns), int(groups)
        self.join_rows, self.pivot_columns = int(join_rows), int(pivot_columns)
        if min(self.rows, self.columns, self.groups, self.join_rows, self.pivot_columns) < 1:
            raise ValueError("analytics limits must be positive")


class Expression:
    def __init__(self, evaluate): self.evaluate = evaluate
    def _binary(self, other, operation):
        right = other if isinstance(other, Expression) else Expression(lambda _row: other)
        def evaluate(row):
            left_value, right_value = self.evaluate(row), right.evaluate(row)
            try:
                return operation(left_value, right_value)
            except TypeError:
                # Explicit SQL-like null comparison semantics: ordered
                # comparisons involving null are false (equality remains a
                # normal Python equality operation and does not raise).
                return False
        return Expression(evaluate)
    def __eq__(self, other): return self._binary(other, lambda a, b: a == b)
    def __ne__(self, other): return self._binary(other, lambda a, b: a != b)
    def __lt__(self, other): return self._binary(other, lambda a, b: a < b)
    def __le__(self, other): return self._binary(other, lambda a, b: a <= b)
    def __gt__(self, other): return self._binary(other, lambda a, b: a > b)
    def __ge__(self, other): return self._binary(other, lambda a, b: a >= b)
    def __and__(self, other): return self._binary(other, lambda a, b: bool(a and b))
    def __or__(self, other): return self._binary(other, lambda a, b: bool(a or b))


def col(name):
    return Expression(lambda row: row.get(name))


def _sort_value(value):
    if value is None: return (2, "", 0)
    if isinstance(value, float) and math.isnan(value): return (1, "float", 0)
    return (0, type(value).__name__, value)


class Table:
    def __init__(self, rows, columns, limits=None):
        self.limits = limits or Limits()
        if len(rows) > self.limits.rows: raise AnalyticsLimitError("row limit exceeded")
        if len(columns) > self.limits.columns: raise AnalyticsLimitError("column limit exceeded")
        self.columns = tuple(columns)
        self._rows = tuple(tuple(row.get(name) for name in self.columns) for row in rows)

    @classmethod
    def from_records(cls, records, limits=None):
        limits = limits or Limits(); rows, names = [], set()
        for record in records:
            if len(rows) >= limits.rows: raise AnalyticsLimitError("row limit exceeded")
            row = dict(record); rows.append(row); names.update(row)
            if len(names) > limits.columns: raise AnalyticsLimitError("column limit exceeded")
        columns = sorted(names)
        return cls(rows, columns, limits)

    @classmethod
    def from_columns(cls, columns, limits=None):
        limits = limits or Limits(); columns = dict(columns)
        if len(columns) > limits.columns: raise AnalyticsLimitError("column limit exceeded")
        lengths = {len(value) for value in columns.values()}
        if len(lengths) > 1: raise ValueError("all columns must have equal length")
        names = sorted(columns); count = next(iter(lengths), 0)
        if count > limits.rows: raise AnalyticsLimitError("row limit exceeded")
        return cls([{name: columns[name][i] for name in names} for i in range(count)], names, limits)

    def to_records(self): return [dict(zip(self.columns, row)) for row in self._rows]
    def to_json(self): return json.dumps(self.to_records(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    def __len__(self): return len(self._rows)
    def _new(self, rows, columns=None): return Table(rows, columns or self.columns, self.limits)

    def select(self, *columns):
        unknown = [name for name in columns if name not in self.columns]
        if unknown: raise KeyError(unknown[0])
        return self._new(self.to_records(), columns)

    def rename(self, **mapping):
        columns = tuple(mapping.get(name, name) for name in self.columns)
        if len(set(columns)) != len(columns): raise ValueError("rename creates duplicate columns")
        return Table([dict(zip(columns, row)) for row in self._rows], columns, self.limits)

    def filter(self, predicate):
        evaluate = predicate.evaluate if isinstance(predicate, Expression) else predicate
        return self._new([row for row in self.to_records() if bool(evaluate(row))])

    def sort_by(self, *columns, reverse=False):
        if not columns: raise ValueError("sort_by requires at least one column")
        for name in columns:
            if name not in self.columns: raise KeyError(name)
        rows = self.to_records()
        rows.sort(key=lambda row: tuple(_sort_value(row.get(name)) for name in columns), reverse=bool(reverse))
        return self._new(rows)

    def group_by(self, *keys): return GroupedTable(self, keys)

    def join(self, other, *, on, how="inner", suffix="_right"):
        keys = (on,) if isinstance(on, str) else tuple(on)
        if how not in ("inner", "left"): raise ValueError("join how must be inner or left")
        index = {}
        for row in other.to_records(): index.setdefault(tuple(row.get(k) for k in keys), []).append(row)
        right_columns = [name for name in other.columns if name not in keys]
        output = []
        for left in self.to_records():
            matches = index.get(tuple(left.get(k) for k in keys), ())
            if not matches and how == "left": matches = [None]
            if len(output) + len(matches) > self.limits.join_rows: raise AnalyticsLimitError("join row limit exceeded")
            for right in matches:
                combined = dict(left)
                for name in right_columns:
                    target = name + suffix if name in combined else name
                    combined[target] = None if right is None else right.get(name)
                output.append(combined)
        return Table.from_records(output, self.limits)

    def pivot(self, *, index, columns, values, aggregate="sum"):
        column_values = sorted({row.get(columns) for row in self.to_records()}, key=_sort_value)
        if len(column_values) > self.limits.pivot_columns: raise AnalyticsLimitError("pivot column limit exceeded")
        labels = [str(value) for value in column_values]
        if len(set(labels)) != len(labels):
            raise ValueError("pivot values produce duplicate string column names")
        buckets = {}
        for row in self.to_records(): buckets.setdefault(row.get(index), {}).setdefault(row.get(columns), []).append(row.get(values))
        output = []
        for index_value in sorted(buckets, key=_sort_value):
            item = {index: index_value}
            for value, label in zip(column_values, labels): item[label] = _aggregate(buckets[index_value].get(value, []), aggregate)
            output.append(item)
        return Table.from_records(output, self.limits)

    def rolling(self, column, *, window, operation="mean", output=None):
        window = int(window)
        if window < 1: raise ValueError("window must be positive")
        if operation not in ("sum", "mean"): raise ValueError("rolling operation must be sum or mean")
        name = output or "%s_%s_%d" % (column, operation, window)
        rows = self.to_records(); values = []
        for index, row in enumerate(rows):
            current = [item.get(column) for item in rows[max(0, index - window + 1):index + 1]]
            values.append(_aggregate(current, operation))
        for row, value in zip(rows, values): row[name] = value
        return Table.from_records(rows, self.limits)

    def record_batches(self, batch_size=100):
        """Explicit bounded serialization for callers persisting to pyre.data."""
        batch_size = int(batch_size)
        if batch_size < 1: raise ValueError("batch_size must be positive")
        rows = self.to_records()
        return [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]


class GroupedTable:
    def __init__(self, table, keys):
        self.table, self.keys = table, tuple(keys)
        if not self.keys: raise ValueError("group_by requires at least one key")
        for key in self.keys:
            if key not in table.columns: raise KeyError(key)

    def aggregate(self, **aggregations):
        groups = {}
        for row in self.table.to_records():
            key = tuple(row.get(name) for name in self.keys)
            if key not in groups and len(groups) >= self.table.limits.groups: raise AnalyticsLimitError("group limit exceeded")
            groups.setdefault(key, []).append(row)
        output = []
        for key in sorted(groups, key=lambda value: tuple(_sort_value(item) for item in value)):
            item = dict(zip(self.keys, key))
            for output_name, spec in sorted(aggregations.items()):
                column, operation = spec
                item[output_name] = _aggregate([row.get(column) for row in groups[key]], operation)
            output.append(item)
        return Table.from_records(output, self.table.limits)


def _aggregate(values, operation):
    if operation == "count": return len(values)
    clean = [value for value in values if value is not None]
    if not clean: return None
    if operation == "sum": return sum(clean)
    if operation == "min": return min(clean)
    if operation == "max": return max(clean)
    if operation in ("mean", "avg"): return sum(clean) / len(clean)
    raise ValueError("unsupported aggregate %r" % operation)
