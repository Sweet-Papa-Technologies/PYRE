"""pyre.data — a thin collections/records layer over pyre.kv (WS-B).

Enough structure to build a CRUD app without hand-rolling key schemes;
explicitly NOT a query database.

    from pyre import data

    foods = data.collection("foods", schema={"name": str, "kcal": int})

    item = foods.insert({"name": "apple", "kcal": 52})   # assigns item["id"]
    item = foods.get(item["id"])
    foods.update(item["id"], {"kcal": 95})               # partial merge
    page = foods.list(limit=20, after=None, where={"name": "apple"})
    foods.delete(item["id"])

Storage model: one kv entry per record under "c:<collection>:<id>", plus a
sequence counter. Ids are zero-padded sequence numbers, so kv's sorted key
order gives stable insertion-ordered pagination.

Schema evolution: pass version=N and a migrate(doc, from_version) function.
Records are migrated lazily on read; the stored copy is rewritten the next
time the record is written. A record's stored version rides in "_v".

    foods = data.collection("foods", schema={"name": str, "kcal": int, "tags": [str]},
                            version=2, migrate=lambda doc, v: {**doc, "tags": []})
"""

from pyre import kv
from pyre.errors import PyreError
from pyre.validation import validate

_ID_WIDTH = 12  # zero-padded sequence ids keep kv's key order == insertion order

# Upper bound on records a single list() call will decode before it stops
# and hands back a cursor. A collection can grow without bound, and
# list(where=...) decodes every candidate it scans; without a cap, a large
# (or attacker-grown) collection drives one query past the per-message
# instruction limit and traps the call — a denial of service. With the cap,
# an unfilled page just returns a `next` cursor so the caller resumes.
MAX_SCAN = 10_000


class Collection:
    def __init__(self, name, schema=None, version=1, migrate=None):
        if ":" in name:
            raise ValueError("collection names cannot contain ':'")
        if version > 1 and migrate is None:
            raise ValueError("version > 1 requires a migrate(doc, from_version) function")
        self.name = name
        self.schema = schema
        self.version = int(version)
        self.migrate = migrate
        self._prefix = "c:%s:" % name
        self._seq_key = "cseq:%s" % name

    # -- internals -----------------------------------------------------------

    def _key(self, record_id):
        return self._prefix + str(record_id)

    def _next_id(self):
        seq = (kv.get(self._seq_key) or 0) + 1
        kv.set(self._seq_key, seq)
        return str(seq).rjust(_ID_WIDTH, "0")

    def _clean(self, doc):
        if self.schema is not None:
            return validate(doc, self.schema)  # raises ValidationError → 400
        if not isinstance(doc, dict):
            raise PyreError("records must be dicts, got %s" % type(doc).__name__)
        return dict(doc)

    def _load(self, record_id, stored):
        """Attach id, apply lazy migration."""
        doc = dict(stored)
        stored_version = doc.pop("_v", 1)
        if stored_version < self.version:
            if self.migrate is None:
                raise PyreError(
                    "collection %r has records at version %d but no migrate function"
                    % (self.name, stored_version)
                )
            doc = self.migrate(doc, stored_version)
        doc["id"] = record_id
        return doc

    def _store(self, record_id, doc):
        stored = {k: v for k, v in doc.items() if k != "id"}
        stored["_v"] = self.version
        kv.set(self._key(record_id), stored)

    # -- CRUD ------------------------------------------------------------------

    def insert(self, doc):
        """Validate and store a new record. Returns it with an assigned id."""
        clean = self._clean(doc)
        record_id = self._next_id()
        self._store(record_id, clean)
        clean["id"] = record_id
        return clean

    def get(self, record_id, default=None):
        stored = kv.get(self._key(record_id))
        if stored is None:
            return default
        return self._load(record_id, stored)

    def replace(self, record_id, doc):
        """Full replace. The record must exist. Persists at current version."""
        if kv.get(self._key(record_id)) is None:
            raise KeyError(record_id)
        clean = self._clean(doc)
        self._store(record_id, clean)
        clean["id"] = record_id
        return clean

    def update(self, record_id, partial):
        """Merge `partial` into the record (migrating it first if needed)."""
        current = self.get(record_id)
        if current is None:
            raise KeyError(record_id)
        merged = {k: v for k, v in current.items() if k != "id"}
        merged.update(partial)
        return self.replace(record_id, merged)

    def delete(self, record_id):
        """Returns True if the record existed."""
        return kv.delete(self._key(record_id))

    # -- listing -------------------------------------------------------------------

    def ids(self):
        prefix_len = len(self._prefix)
        found = [k[prefix_len:] for k in kv.keys() if k.startswith(self._prefix)]
        return sorted(found)

    def count(self):
        return len(self.ids())

    def list(self, limit=20, after=None, where=None, max_scan=None):
        """Insertion-ordered page: {"items": [...], "next": cursor-or-None}.

        `after` is the cursor from the previous page's "next". `where` is a
        dict of exact-match field filters, applied while scanning (MVP: this
        is an O(collection) scan, fine for small app data).

        The scan decodes at most `max_scan` records (default MAX_SCAN) per
        call. If that budget is hit before the page fills — e.g. a `where`
        filter that matches few records in a large collection — the call
        returns the items found so far plus a `next` cursor at the last
        record examined, so the caller resumes with `after=next` instead of
        the framework doing unbounded work (and risking an instruction-limit
        trap) in a single message. `next is None` still means "end reached".
        """
        limit = max(1, int(limit))
        budget = MAX_SCAN if max_scan is None else max(1, int(max_scan))
        items = []
        next_cursor = None
        scanned = 0
        last_seen = None
        for record_id in self.ids():
            if after is not None and record_id <= after:
                continue
            if len(items) == limit:
                next_cursor = items[-1]["id"]
                break
            if scanned >= budget:
                # Budget exhausted before the page filled: resume from the
                # last record we examined rather than scanning further now.
                next_cursor = last_seen
                break
            scanned += 1
            last_seen = record_id
            doc = self.get(record_id)
            if where and any(doc.get(k) != v for k, v in where.items()):
                continue
            items.append(doc)
        else:
            next_cursor = None
        return {"items": items, "next": next_cursor}


def collection(name, schema=None, version=1, migrate=None):
    return Collection(name, schema=schema, version=version, migrate=migrate)
