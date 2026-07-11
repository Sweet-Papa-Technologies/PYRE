"""Supabase (PostgREST) over ICP HTTPS outcalls.

    from pyre.adapters import supabase

    db = supabase.Client(url=SUPA_URL, anon_key=SUPA_KEY)

    @app.get("/external", update=True)
    async def external(req):
        rows = await db.table("items").select().eq("done", "false").limit(10)
        return Response.json(rows)

    @app.post("/mirror", update=True)
    async def mirror(req):
        row = {"id": prandom.uuid4(), "title": req.json["title"]}
        await db.table("items").upsert(row)      # idempotent under fan-out
        return Response.json(row, status=201)

Platform constraints this adapter designs around (read once, then it's
handled for you):

  AMPLIFICATION — one canister outcall is executed by every replica on
  the subnet (~13x measured), so every write hits Supabase ~13 times.
  Plain INSERT with a database-generated id would create ~13 rows.
  Therefore `insert()` here REQUIRES client-supplied primary keys and
  rides PostgREST upserts (`resolution=merge-duplicates`), making the
  13 deliveries converge to one row. Generate ids with pyre.random's
  uuid4() — consensus-safe, identical across replicas.

  METHODS — outcalls support GET/HEAD/POST only. PostgREST's PATCH and
  DELETE verbs are unreachable; updates are expressed as upserts, and
  deletes go through a Postgres function you expose via `rpc()`:

      create function delete_item(item_id uuid) returns void
      language sql security definer as
      $$ delete from items where id = item_id $$;

      await db.rpc("delete_item", {"item_id": item_id})

  (RPC calls are POSTs, so they are amplified too — make functions
  idempotent, which deletes-by-id naturally are.)

  DETERMINISM — replicas must agree byte-for-byte on the response.
  Volatile headers are stripped by the default transform; body bytes
  are whatever PostgREST returns, which is stable for stable data. A
  read racing a concurrent external write can land on both sides of it
  across replicas and fail consensus — treat that as a retry, and keep
  the standing rule: integration, not hot path.

Auth note: the anon/service key sits in canister memory and travels in
request headers, both visible to node operators — same standing
limitation as all secret-bearing outcalls (docs/secrets-and-outcalls.md).
Use an anon key plus Postgres row-level security, not your service key,
unless you accept that exposure.
"""

import json as _json

from pyre.errors import PyreError
from pyre.outcall import DEFAULT_MAX_RESPONSE_BYTES, OutcallFuture
from pyre.compat.urllib_request import default_transform


class SupabaseError(PyreError):
    """PostgREST returned an error response."""
    code = "PYRE-SUPABASE"

    status = 502

    def __init__(self, message, http_status=None, details=None):
        super().__init__(message)
        self.http_status = http_status
        self.details = details


class Client:
    """One Supabase project. Cheap to construct; hold it at module level."""

    def __init__(self, url, anon_key, *, schema="public",
                 max_response_bytes=DEFAULT_MAX_RESPONSE_BYTES,
                 cycles=None, transform=default_transform):
        self.base = url.rstrip("/")
        self.anon_key = anon_key
        self.schema = schema
        self.max_response_bytes = max_response_bytes
        self.cycles = cycles
        self.transform = transform

    def table(self, name):
        return Table(self, name)

    def rpc(self, function, args=None, *, max_response_bytes=None):
        """Call a Postgres function: POST /rest/v1/rpc/<function>.

        The escape hatch for anything POST-shaped semantics can't
        express directly (deletes, bulk updates, transactions).
        """
        return _Query(
            self, "POST", "/rest/v1/rpc/" + function,
            body=_json.dumps(args or {}),
            max_response_bytes=max_response_bytes,
        )

    def _headers(self, extra=None):
        headers = {
            "apikey": self.anon_key,
            "authorization": "Bearer " + self.anon_key,
            "content-type": "application/json",
            "accept-profile": self.schema,
            "content-profile": self.schema,
        }
        if extra:
            headers.update(extra)
        return headers


class Table:
    def __init__(self, client, name):
        self._client = client
        self._name = name

    def select(self, columns="*"):
        """Start a read. Chain filters, then await it."""
        return _Query(self._client, "GET", "/rest/v1/" + self._name,
                      params=[("select", columns)])

    def insert(self, rows, *, on_conflict=None, returning="representation"):
        """Idempotent insert (upsert) of one row or a list of rows.

        Every row MUST carry its primary key (client-generated — use
        pyre.random's uuid4()); the ~13x outcall fan-out then merges to
        one row instead of creating ~13. `on_conflict` names the key
        column(s) when the primary key alone isn't the conflict target.
        """
        if isinstance(rows, dict):
            rows = [rows]
        prefer = "resolution=merge-duplicates"
        if returning:
            prefer += ",return=" + returning
        params = [("on_conflict", on_conflict)] if on_conflict else []
        return _Query(self._client, "POST", "/rest/v1/" + self._name,
                      params=params, body=_json.dumps(rows),
                      headers={"prefer": prefer})

    # The honest name for what insert() does; both are the same upsert.
    upsert = insert

    def update(self, values, *, key, returning="representation"):
        """Update-by-upsert (PATCH is unreachable over outcalls).

        `values` must include the row's key column (`key`); on conflict
        PostgREST merges the provided columns into the existing row,
        leaving unspecified columns untouched. Idempotent under fan-out.
        """
        if key not in values:
            raise PyreError("update() needs the primary key %r in values" % key)
        return self.insert(values, on_conflict=key, returning=returning)

    def delete(self, **_kw):
        raise PyreError(
            "PostgREST deletes need the DELETE verb, which ICP outcalls "
            "don't support (GET/HEAD/POST only). Expose a SQL function and "
            "call db.rpc('delete_item', {...}) — see the module docstring."
        )


# RFC 3986 unreserved + the characters PostgREST operators rely on.
_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "-._~*,().:"
)


def _quote(text):
    """Percent-encode a query-string component (pure Python, no urllib)."""
    out = []
    for byte in text.encode("utf-8"):
        ch = chr(byte)
        out.append(ch if ch in _SAFE else "%%%02X" % byte)
    return "".join(out)


class _Query:
    """A composable, awaitable PostgREST request."""

    def __init__(self, client, method, path, params=None, body=None,
                 headers=None, max_response_bytes=None):
        self._client = client
        self._method = method
        self._path = path
        self._params = list(params or [])
        self._body = body
        self._headers = headers or {}
        self._max_response_bytes = max_response_bytes
        self._single = False

    # -- filters (PostgREST operators) --------------------------------

    def _op(self, column, op, value):
        self._params.append((column, "%s.%s" % (op, value)))
        return self

    def eq(self, column, value):
        return self._op(column, "eq", value)

    def neq(self, column, value):
        return self._op(column, "neq", value)

    def gt(self, column, value):
        return self._op(column, "gt", value)

    def gte(self, column, value):
        return self._op(column, "gte", value)

    def lt(self, column, value):
        return self._op(column, "lt", value)

    def lte(self, column, value):
        return self._op(column, "lte", value)

    def like(self, column, pattern):
        return self._op(column, "like", pattern)

    def in_(self, column, values):
        joined = ",".join(str(v) for v in values)
        self._params.append((column, "in.(%s)" % joined))
        return self

    def is_(self, column, value):  # null / true / false
        return self._op(column, "is", value)

    def order(self, column, desc=False):
        self._params.append(("order", column + (".desc" if desc else ".asc")))
        return self

    def limit(self, n):
        self._params.append(("limit", str(int(n))))
        return self

    def offset(self, n):
        self._params.append(("offset", str(int(n))))
        return self

    def single(self):
        """Expect exactly one row; await evaluates to a dict, not a list."""
        self._single = True
        return self

    # -- execution ------------------------------------------------------

    def _url(self):
        url = self._client.base + self._path
        if self._params:
            pairs = []
            for k, v in self._params:
                pairs.append("%s=%s" % (_quote(str(k)), _quote(str(v))))
            url += "?" + "&".join(pairs)
        return url

    def _future(self):
        return OutcallFuture(
            url=self._url(),
            method=self._method,
            data=self._body,
            headers=self._client._headers(self._headers),
            transform_name=self._client.transform,
            max_response_bytes=self._max_response_bytes
            or self._client.max_response_bytes,
            cycles=self._client.cycles,
            raise_for_status=False,
        )

    def _gen(self):
        resp = yield self._future()
        if resp.status >= 400:
            details = None
            message = "supabase: HTTP %d on %s %s" % (
                resp.status, self._method, self._path)
            try:
                details = resp.json()
                if isinstance(details, dict) and details.get("message"):
                    message += " — " + str(details["message"])
            except Exception:
                pass
            raise SupabaseError(message, http_status=resp.status, details=details)
        if resp.status == 204 or not resp.read():
            return None
        data = resp.json()
        if self._single:
            if not isinstance(data, list) or len(data) != 1:
                raise SupabaseError(
                    "expected exactly one row, got %s"
                    % (len(data) if isinstance(data, list) else type(data).__name__),
                    http_status=resp.status,
                )
            return data[0]
        return data

    def __await__(self):
        return self._gen()

    def __iter__(self):
        return self._gen()
