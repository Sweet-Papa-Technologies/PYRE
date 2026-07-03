"""Comment model: pyre.data collection + kv rate-limit counters.

Storage layout:
- collection "comments" (schema below, version=1) — the comment documents.
  status is one of pending|approved|rejected; only *approved* comments are
  ever served publicly (and they are served certified — see app.py).
- kv "cpending:<author_sub>" -> int   (# of still-pending comments by an
  author; the per-identity backlog cap. Incremented on submit, decremented
  when a pending comment is approved or rejected.)
- kv "crate:<author_sub>:<hour>" -> int  (submissions in a wall-clock hour
  bucket; the per-identity throughput cap. Cheap sliding-ish window.)

Untrusted input + identity (SPEC §7 risk row) is contained by: authenticated
submit only (enforced in app.py via a valid session), author moderation
(nothing renders until approved), a hard body size cap, and per-identity
rate limits — never improvised auth.
"""

from datetime import datetime

from pyre import data, kv
from pyre import ptime

SCHEMA_VERSION = 1

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)

# Body size cap: reject anything over this many characters (SPEC §4 Phase C).
MAX_BODY_CHARS = 2000

# Per-identity rate limits (SPEC §4 Phase C — "max N pending or M/hour").
MAX_PENDING_PER_AUTHOR = 5      # unreviewed backlog cap
MAX_PER_HOUR_PER_AUTHOR = 10    # throughput cap

comments = data.collection(
    "comments",
    schema={
        "slug": str,
        "author_sub": str,       # OIDC subject — the stable identity
        "author_name": str,
        "author_email": str,
        "body": str,
        "ts": (int, 0),          # epoch seconds
        "status": str,
    },
    version=SCHEMA_VERSION,
)


class BodyTooLong(Exception):
    """Comment body exceeds MAX_BODY_CHARS."""


class RateLimited(Exception):
    """Author has too many pending comments or too many this hour."""


# -- rate-limit counters (kv) --------------------------------------------------


def _pending_key(sub):
    return "cpending:%s" % sub


def _hour_bucket(now):
    return now // 3600


def _rate_key(sub, now):
    return "crate:%s:%d" % (sub, _hour_bucket(now))


def pending_count(sub):
    return kv.get(_pending_key(sub)) or 0


def _incr_pending(sub, delta):
    kv.set(_pending_key(sub), max(0, pending_count(sub) + delta))


def submissions_this_hour(sub, now):
    return kv.get(_rate_key(sub, now)) or 0


# -- submit --------------------------------------------------------------------


def submit(slug, author_sub, author_name, author_email, body, now=None):
    """Store a new pending comment. Raises ValueError (empty), BodyTooLong,
    or RateLimited. Returns the stored doc."""
    text = (body or "").strip()
    if not text:
        raise ValueError("comment body is empty")
    if len(text) > MAX_BODY_CHARS:
        raise BodyTooLong(
            "comment body is %d chars; the limit is %d"
            % (len(text), MAX_BODY_CHARS)
        )
    current = ptime.now() if now is None else int(now)
    if pending_count(author_sub) >= MAX_PENDING_PER_AUTHOR:
        raise RateLimited(
            "you have %d comments awaiting moderation (max %d); wait for the "
            "author to review them" % (pending_count(author_sub), MAX_PENDING_PER_AUTHOR)
        )
    if submissions_this_hour(author_sub, current) >= MAX_PER_HOUR_PER_AUTHOR:
        raise RateLimited(
            "rate limit: at most %d comments per hour" % MAX_PER_HOUR_PER_AUTHOR
        )

    doc = comments.insert({
        "slug": slug,
        "author_sub": author_sub,
        "author_name": author_name or "",
        "author_email": author_email or "",
        "body": text,
        "ts": current,
        "status": STATUS_PENDING,
    })
    _incr_pending(author_sub, +1)
    kv.set(_rate_key(author_sub, current), submissions_this_hour(author_sub, current) + 1)
    return doc


# -- moderation ----------------------------------------------------------------


def get(comment_id):
    return comments.get(comment_id)


def set_status(comment_id, status):
    """Transition a comment's status. Returns the updated doc, or None if the
    id is unknown. Keeps the per-author pending counter in sync."""
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % (STATUSES,))
    doc = comments.get(comment_id)
    if doc is None:
        return None
    if doc["status"] == STATUS_PENDING and status != STATUS_PENDING:
        _incr_pending(doc["author_sub"], -1)
    saved = comments.update(comment_id, {"status": status})
    return saved


def approve(comment_id):
    return set_status(comment_id, STATUS_APPROVED)


def reject(comment_id):
    return set_status(comment_id, STATUS_REJECTED)


# -- listing -------------------------------------------------------------------


def _all():
    return [comments.get(cid) for cid in comments.ids()]


def approved_for_slug(slug):
    """Approved comments for a post, oldest first (thread reading order)."""
    docs = [
        d for d in _all()
        if d["slug"] == slug and d["status"] == STATUS_APPROVED
    ]
    docs.sort(key=lambda d: (d["ts"], d["id"]))
    return docs


def pending():
    """All pending comments across posts, newest first (moderation queue)."""
    docs = [d for d in _all() if d["status"] == STATUS_PENDING]
    docs.sort(key=lambda d: (d["ts"], d["id"]), reverse=True)
    return docs


# -- public JSON shape ---------------------------------------------------------


def _iso(epoch):
    return datetime.utcfromtimestamp(int(epoch)).isoformat() + "Z"


def public_comment(doc):
    """Wire shape aligned with the frontend `Comment` type
    (frontend/src/api/types.ts): author_identity is the OIDC sub, ts is an
    ISO-8601 string. author_email is intentionally NOT exposed publicly."""
    return {
        "id": doc["id"],
        "slug": doc["slug"],
        "author_identity": doc["author_sub"],
        "author_name": doc["author_name"],
        "body": doc["body"],
        "ts": _iso(doc["ts"]),
        "status": doc["status"],
    }
