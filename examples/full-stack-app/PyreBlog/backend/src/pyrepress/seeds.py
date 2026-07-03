"""Demo content: 3 published posts (incl. the PYRE announcement) + 1 draft.

Loaded via POST /api/seed (bearer-gated, idempotent by slug) — or from
scripts/seed.sh, which just curls that route.
"""

from pyrepress import posts as model

ANNOUNCEMENT_MD = """\
Today [Sweet Papa Technologies](https://sweetpapatechnologies.com) is releasing
**PYRE v1.1** — a Flask-flavored Python framework that runs your backend
*inside* an [Internet Computer](https://internetcomputer.org) canister.
`pip install pyre-icp`, write routes you already know how to write, and deploy
an API whose responses clients can cryptographically verify. Source and docs
live at [github.com/Sweet-Papa-Technologies/PYRE](https://github.com/Sweet-Papa-Technologies/PYRE).

## Why bother?

A normal API says *trust me*. A PYRE API says *check me*: certified GET
routes are served with an `IC-Certificate` header that verifies against the
network's root of trust, not against the server that answered. This post is
itself the demo — it's stored in a canister, rendered to HTML in-canister,
and served as a certified response. Tamper with the canister's answer and
verification fails. (Click "verify this post" to check for yourself.)

## What's in the box

- **Flask-style routing** — `@app.get`, `@app.post`, path params, hooks,
  CORS, validation. No Candid, no Rust, no Motoko.
- **Certified reads** — `@app.get(path, certified=True)` snapshot-certifies
  a route; the framework recertifies automatically after every state change.
- **A real data layer** — `pyre.data` collections over stable memory:
  schema-validated, versioned with lazy migration, and they survive upgrades.
- **Outbound HTTPS that looks like urllib** — with the determinism transform
  ICP's replicated execution requires applied for you.
- **Threshold-signed JWTs** — the subnet signs cooperatively (tECDSA);
  there is no private key on any machine to steal.
- **Defused footguns** — naive `uuid4()`, `os.urandom`, and `secrets` are
  constant stubs in a replicated WASM runtime. PYRE makes them fail loudly
  and gives you `pyre.random`, `pyre.uuid`, and `pyre.time` instead.

## The numbers

Measured on mainnet: a light backend costs **about $0.40/month** in cycles;
certified query dispatch runs around 97k cycles. Getting a canister created
and the Python runtime installed is roughly a one-time $2.

## The stack

PYRE targets Kybra 0.7.1 (RustPython, Python 3.10) and dfx. Everything is
pure Python on your side: `pyre new myapp --template crud-kv`, `pyre dev`
for instant local iteration, `dfx deploy` when you mean it.

Python on the Internet Computer, verified. Go build something tamper-proof.
"""

HELLO_MD = """\
Welcome to **PyrePress** — a blog whose posts are certified by the network
that serves them.

This post exercises the markdown subset:

## A heading

Some *italic*, some **bold**, some `inline code`, and a
[link](https://github.com/Sweet-Papa-Technologies/PYRE).

```python
from pyre import App
app = App()

@app.get("/health", certified=True)
def health(req):
    return {"status": "ok"}
```

- an unordered list
- with a second item

1. an ordered list
2. with a second item

> A blockquote, for good measure.

---

Raw HTML like <script>alert("nope")</script> is escaped, never executed.

![PYRE banner](https://raw.githubusercontent.com/Sweet-Papa-Technologies/PYRE/main/img/pyre-larger-banner.jpg)
"""

CERTIFIED_MD = """\
When you `GET` a post from PyrePress, the response carries an
`IC-Certificate` header. Your client can verify — against the Internet
Computer's public root key — that the bytes you received are exactly the
bytes the canister committed. Not TLS ("the pipe was private") but
*content* certification ("the answer is authentic").

The flow, roughly:

1. On every state change the canister re-renders each certified route and
   commits the hash tree's root via `set_certified_data`.
2. The subnet countersigns that root during consensus.
3. Your response includes the certificate + a hash-tree witness proving the
   body you got is in the certified tree.

Try it: fetch any post with `curl -i` and look for the header, or run the
verifier linked in the post's `verify` block.
"""

DRAFT_MD = """\
Ideas for Phase B/C (not published):

- OIDC comments (hard gate: RS256 verify in-canister)
- Internet Identity fallback
- `pyre new --template blog`
"""

SEED_POSTS = [
    {
        "title": "PYRE v1.1: Python on the Internet Computer, verified",
        "slug": "pyre-v1-1-announcement",
        "markdown": ANNOUNCEMENT_MD,
        "tags": ["pyre", "icp", "release"],
        "status": "published",
    },
    {
        "title": "Hello, PyrePress",
        "slug": "hello-pyrepress",
        "markdown": HELLO_MD,
        "tags": ["meta"],
        "status": "published",
    },
    {
        "title": "What a certified read actually proves",
        "slug": "what-certified-reads-prove",
        "markdown": CERTIFIED_MD,
        "tags": ["icp", "certification"],
        "status": "published",
    },
    {
        "title": "Roadmap notes (draft)",
        "slug": "roadmap-notes",
        "markdown": DRAFT_MD,
        "tags": ["meta"],
        "status": "draft",
    },
]


def load():
    """Insert any seed post whose slug doesn't exist yet. Returns slugs created."""
    created = []
    for spec in SEED_POSTS:
        if model.id_for_slug(spec["slug"]) is not None:
            continue
        model.create_post(
            title=spec["title"],
            markdown=spec["markdown"],
            slug=spec["slug"],
            tags=spec["tags"],
            status=spec["status"],
        )
        created.append(spec["slug"])
    return created
