"""Post model: pyre.data collection + kv slug index + kv view counters.

Storage layout:
- collection "posts" (schema below, version=1) — the post documents.
- kv "slugidx:<slug>" -> post id             (unique-slug enforcement, O(1) lookup)
- kv "views:<post-id>" -> int                 (HOT write path: view counts live
  OUTSIDE the post document so `POST .../view` never rewrites the post)

Newest-first listing and tag filtering are done app-side:
`data.Collection.list()` only offers ascending insertion order and
exact-match `where=` (a list field can't be matched by membership), so we
scan `ids()` and sort by (published_at, id) desc — O(n), fine at blog scale.
"""

import re

from pyre import data, kv
from pyre import time as ptime

from pyrepress.renderer import render_markdown

SCHEMA_VERSION = 1

# "query" is routed as GET /api/posts/query (the uncertified list variant),
# so it can never be a post slug.
RESERVED_SLUGS = {"query"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SLUG_LEN = 100

STATUSES = ("draft", "published")


class SlugInvalid(Exception):
    pass


class SlugTaken(Exception):
    pass


posts = data.collection(
    "posts",
    schema={
        "slug": str,
        "title": str,
        "markdown": str,
        "html": str,
        "tags": [str],
        "status": str,
        "published_at": (int, 0),  # epoch seconds; 0 = never published
        "updated_at": (int, 0),
    },
    version=SCHEMA_VERSION,
)


# -- slugs --------------------------------------------------------------------


def slugify(title):
    """'PYRE v1.1: Python, verified!' -> 'pyre-v1-1-python-verified'."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    slug = slug[:MAX_SLUG_LEN].strip("-")
    return slug or "post"


def check_slug(slug):
    """Raise SlugInvalid unless slug matches the rules."""
    if (
        not isinstance(slug, str)
        or len(slug) > MAX_SLUG_LEN
        or not SLUG_RE.match(slug)
    ):
        raise SlugInvalid(
            "slugs are lowercase letters/digits separated by single dashes "
            "(max %d chars): %r" % (MAX_SLUG_LEN, slug)
        )
    if slug in RESERVED_SLUGS:
        raise SlugInvalid("%r is a reserved path segment" % slug)


def _slug_key(slug):
    return "slugidx:%s" % slug


def id_for_slug(slug):
    return kv.get(_slug_key(slug))


def get_by_slug(slug):
    record_id = id_for_slug(slug)
    if record_id is None:
        return None
    return posts.get(record_id)


# -- view counters (hot path: never touches the post document) ----------------


def _views_key(post_id):
    return "views:%s" % post_id


def views(post_id):
    return kv.get(_views_key(post_id)) or 0


def incr_views(post_id):
    count = views(post_id) + 1
    kv.set(_views_key(post_id), count)
    return count


# -- CRUD ----------------------------------------------------------------------


def create_post(title, markdown, slug=None, tags=None, status="draft"):
    """Insert a new post. Raises SlugInvalid / SlugTaken / ValueError."""
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % (STATUSES,))
    slug = slug or slugify(title)
    check_slug(slug)
    if id_for_slug(slug) is not None:
        raise SlugTaken(slug)
    now = ptime.now()
    doc = posts.insert(
        {
            "slug": slug,
            "title": title,
            "markdown": markdown,
            "html": render_markdown(markdown),
            "tags": list(tags or []),
            "status": status,
            "published_at": now if status == "published" else 0,
            "updated_at": now,
        }
    )
    kv.set(_slug_key(slug), doc["id"])
    return doc


def update_post(slug, changes):
    """Partial update; `changes` may include title/markdown/tags/status/slug.

    Returns (old_doc, new_doc). Raises KeyError if the slug is unknown,
    SlugInvalid/SlugTaken on a bad rename, ValueError on a bad status.
    """
    old = get_by_slug(slug)
    if old is None:
        raise KeyError(slug)
    doc = dict(old)

    if "status" in changes and changes["status"] not in STATUSES:
        raise ValueError("status must be one of %s" % (STATUSES,))

    new_slug = changes.get("slug", slug)
    if new_slug != slug:
        check_slug(new_slug)
        if id_for_slug(new_slug) is not None:
            raise SlugTaken(new_slug)

    for field in ("title", "markdown", "tags", "status", "slug"):
        if field in changes:
            doc[field] = changes[field]
    if "markdown" in changes:
        doc["html"] = render_markdown(doc["markdown"])
    if doc["status"] == "published" and old["published_at"] == 0:
        doc["published_at"] = ptime.now()  # first publish
    doc["updated_at"] = ptime.now()

    saved = posts.replace(old["id"], {k: v for k, v in doc.items() if k != "id"})
    if new_slug != slug:
        kv.delete(_slug_key(slug))
        kv.set(_slug_key(new_slug), old["id"])
    return old, saved


def delete_post(slug):
    """Returns the deleted doc, or None if the slug is unknown."""
    doc = get_by_slug(slug)
    if doc is None:
        return None
    posts.delete(doc["id"])
    kv.delete(_slug_key(slug))
    kv.delete(_views_key(doc["id"]))
    return doc


# -- listing --------------------------------------------------------------------


def all_posts():
    return [posts.get(record_id) for record_id in posts.ids()]


def published_posts():
    """All published posts, newest first (published_at desc, id desc)."""
    docs = [d for d in all_posts() if d["status"] == "published"]
    docs.sort(key=lambda d: (d["published_at"], d["id"]), reverse=True)
    return docs


def list_published(limit=10, after=None, tag=None):
    """Newest-first page of published posts.

    `after` is a post id cursor (the `next` from the previous page);
    `tag` filters by membership in tags[].
    """
    limit = max(1, min(int(limit), 100))
    docs = published_posts()
    if tag:
        docs = [d for d in docs if tag in d["tags"]]
    start = 0
    if after is not None:
        for i, d in enumerate(docs):
            if d["id"] == after:
                start = i + 1
                break
        else:
            start = len(docs)  # unknown cursor: empty page, not an error
    page = docs[start : start + limit]
    has_more = start + limit < len(docs)
    return {"items": page, "next": page[-1]["id"] if page and has_more else None}


# -- public JSON shapes -----------------------------------------------------------


def public_post(doc, include_markdown=True):
    """The wire shape: post fields + live view count (never stored in doc)."""
    out = {
        "id": doc["id"],
        "slug": doc["slug"],
        "title": doc["title"],
        "html": doc["html"],
        "tags": doc["tags"],
        "status": doc["status"],
        "published_at": doc["published_at"],
        "updated_at": doc["updated_at"],
        "views": views(doc["id"]),
    }
    if include_markdown:
        out["markdown"] = doc["markdown"]
    return out
