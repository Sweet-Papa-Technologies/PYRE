# PyrePress DX friction log

Building the first real app on the **published** `pyre-icp` (1.1.2), installed
as a user would (`pip install pyre-icp kybra==0.7.1` in a fresh pyenv-3.10.7
venv), deploying to a local replica with dfx 0.32. Severity tags: **HIGH**
(blocks a documented workflow), **MEDIUM** (surprising, needs a workaround),
**LOW** (polish / docs).

The install itself was clean: `pip install pyre-icp kybra==0.7.1`,
`python -m kybra install-dfx-extension`, `pyre new --template crud-kv`,
`pyre dev`, `dfx deploy` all worked as documented. The friction below is
everything that tripped me after that.

---

## 1. HIGH — `pyre.log` 500s every logging handler under `pyre dev`

`pyre.log._print` is:

```python
def _print(line):
    try:
        from kybra import ic      # lazy: canister runtime only
        ic.print(line)
    except ImportError:
        import sys; print(line, file=sys.stderr)
```

The quickstart tells you to `pip install ... kybra==0.7.1` into the same venv
you run `pyre dev` from. So on the host **`from kybra import ic` succeeds** —
and then `ic.print(line)` raises `NameError: name '_kybra_ic' is not defined`
(kybra's `ic` proxy only binds inside the canister). That is **not** an
`ImportError`, so it escapes, and PYRE turns it into a `500 internal server
error` for **any handler that calls `log.info/…`**. My `POST /posts` and
`POST .../publish` handlers both 500'd in dev while silently succeeding at the
data write — the most confusing possible failure mode.

- **Impact:** the documented dev loop is broken for any handler that logs.
- **Workaround (shipped):** a `_safe_log()` wrapper (`try/except Exception`).
- **Fix:** `_print` should `except Exception` (or gate on
  `pyre.in_canister()`), not `except ImportError`.

## 2. HIGH — uncertified GET routes 503 through the certifying gateway

Once the canister certifies *any* exact paths, the ICP response-verification
**v2 boundary node** rejects uncertified GET responses served via PYRE's
skip-certification wildcard:

```
503 backend_response_verification
"A wildcard expression path (["http_expr","<*>"]) was provided, but a
 potential exact expression path (["http_expr","api","posts","query","<$>"])
 is valid for the request path and might exist in the tree"
```

PYRE serves uncertified routes with the `["http_expr","<*>"]` witness, but the
gateway demands proof that the *more specific* path is **absent** from the
tree, and PYRE's pruned witness doesn't provide it. Result: `GET
/api/posts/query` (pagination + tag filter) and draft previews **fail on
`<cid>.localhost:4943` and `icp0.io`** — they only work on the `raw`
subdomain (which skips verification). Certified routes (`/api/posts`,
`/api/posts/<slug>`, `/api/feed.xml`, `/api/health`) are fine.

- **Impact:** "certify some routes, serve the rest uncertified" — the natural
  mental model — doesn't hold behind a verifying gateway. Anything not
  certified needs the `raw` domain or must be made certified.
- **Workaround (shipped):** documented in API.md — the frontend hits
  uncertified endpoints via `raw`, or filters/paginates client-side from the
  certified `/api/posts`. The certified core (single post, list, feed) is
  unaffected.
- **Fix:** PYRE's `skip_headers` witness needs to prove absence along the
  requested path (an `<*>`-at-each-level pruning), not just reveal the root
  `<*>` leaf. This is the single most important framework finding here.

## 3. MEDIUM — no pip Markdown renderer bundles under RustPython

Confirmed exactly as the spec warned. `markdown` imports
`importlib.metadata` → broken in the stdlib matrix (`os.chmod` missing).
`mistune` / `markdown-it-py` are pure-Python but betting their whole import
closure survives RustPython is a gamble, and they add WASM weight for a
feature a blog uses a subset of. (An earlier draft of this backend imported
`mistune`, which wasn't even installed — the app wouldn't import.) **Shipped a
~150-line pure-Python subset renderer** (`pyrepress/renderer.py`, only `re` +
`html`) — it renders and sanitizes identically on host and in-canister, which
I verified on the replica (the announcement's `<strong>/<a>/<h2>` are produced
in-canister).

- **Fix / ask:** ship a blessed `pyre.markdown` (or a documented recipe) so
  every blog-shaped app doesn't re-derive this. The "just pip install X"
  reflex fails silently here; `docs/stdlib-matrix.md` is load-bearing and
  should link a renderer recommendation.

## 4. MEDIUM — certified routes silently ignore the query string

A certified route serves its frozen snapshot **keyed by path**, ignoring
`?params`. So a single certified `GET /api/posts?tag=x` would return the
**unfiltered** certified page with no error — a correctness trap. You must
split into a certified canonical route (no params) + a separate uncertified
query route… which then runs straight into finding #2. Worth a bold docs
callout next to `certified=True`.

## 5. MEDIUM — per-resource certification is a hand-rolled pattern

PYRE certifies **static route paths** only, and `recertify()` re-renders each
certified route by its *literal* path. There is no first-class "certify this
dynamic resource." To get a tamper-proof `GET /posts/{slug}` you must:

1. register one **static** certified route per published slug at publish time,
2. move it ahead of the parametric `/posts/{slug}` route (first-match wins),
3. rebuild the whole set at `@init`/`@post_upgrade` (runtime-registered routes
   live in heap and **don't survive an upgrade**; the data does).

It works — I verified certified single-post reads survive an upgrade — but
it's entirely undocumented and easy to get wrong (esp. the upgrade rebuild).
A `app.certify_path(path, render_fn)` primitive, or docs for this pattern,
would save every content-shaped app from rediscovering it.

## 6. LOW — `pyre new` says "never edit main.py", but you must

The generated `main.py` header says "you normally never edit it." Per-post
certification **required** editing `@init`/`@post_upgrade` to call
`sync_certified_routes()` before `recertify()` (kv isn't bound at module
import, so state-derived routes can only be built at init). The "never edit
main.py" guidance breaks the moment you need init-time, state-derived route
registration.

## 7. LOW — venv/dfx interaction is fragile

- A shell alias `python=/usr/bin/python3` shadowed the **activated** venv;
  the kybra dfx extension then couldn't find kybra and `dfx deploy` failed
  confusingly. Had to `unalias python` after `source .venv/bin/activate`.
- `dfx ping` intermittently reported *"cannot connect to the local replica"*
  from the project subdir while succeeding from the repo root seconds earlier
  (transient replica reconnect). Noise that reads like a real error.

## 8. LOW — `verify_certification.py` needs an undocumented 4th arg on macOS

The script's docstring shows `verify_certification.py <url> <canister_id>`,
but Python's `urllib` can't resolve `<cid>.localhost` on macOS
(`socket.gaierror`), so you must pass the **4th** `connect` arg
(`127.0.0.1:4943`) — which isn't in the usage line. With it, verification of
the certified post **PASSES** end-to-end (expr_path, response-hash-in-leaf,
witness-root == certified_data). Great tool; fix the usage string.

---

## What was genuinely good (the DX wins)

- **`pyre dev` is an instant, real loop** — same routing code as the canister,
  query/update rules enforced locally; caught my logic bugs before any deploy.
- **`pyre.data` collections** — schema validation, versioning + lazy migrate,
  and upgrade-survival with zero ceremony. The blog's whole model is ~1 file.
- **Certified reads for static routes "just work"** — `certified=True` and the
  automatic post-update `recertify()` are genuinely one line; the hard crypto
  is invisible.
- **`scripts/verify_certification.py`** independently proved the in-canister-
  rendered post is untampered — the exact "check me, don't trust me" story the
  app is selling.
- **Deploy was fast** — the Rust runtime layer cached; iterating on Python
  rebuilt the wasm in ~18s.
