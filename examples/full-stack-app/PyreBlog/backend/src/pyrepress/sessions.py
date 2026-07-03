"""Cheap stored sessions (Phase C).

SPEC §4 Phase C + §6 are emphatic that sessions must be CHEAP:

- On a successful OIDC login we mint a session id from
  `await pyre.random.raw_bytes(32)` (tier-2 threshold-BLS entropy — an
  unguessable, consensus-safe token) and store

      session_id -> {identity, email, name, picture, provider,
                     created_at, expires_at}

  We do **NOT** threshold-sign the session (§3 non-goal / §6: signing is
  ~$0.035 each — ruinous per-login). The stored-random-token model is the
  old, cheap answer: issuing rides one update call, validation is a read.

- Session VALIDATION is a pure READ, so it stays query-fast: one O(1) kv
  lookup keyed by the token, plus an expiry check against pyre.time. That
  is why sessions live in **kv keyed by the session id** rather than in a
  data.collection — a collection assigns its own sequence ids, so finding a
  record by session token would require an O(n) scan. kv gives the direct
  O(1) `get(session:<id>)` the query path needs.

Sessions expire after SESSION_TTL_SECONDS (default 30 days); an expired
record fails validation (and is lazily deleted on the next update-context
touch — a query can't write).

The token is read from the `X-Session-Id` request header (canonical, what
the frontend sends) or, as a fallback, `Authorization: Bearer <session_id>`.
"""

from pyre import kv
from pyre import ptime
from pyre import random as prandom

# 30 days. Long enough that a reader isn't re-prompted mid-thread; short
# enough that a leaked token isn't forever. Consensus time is coarse but
# more than good enough for day-granularity expiry (§6).
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60

# 32 bytes of threshold-BLS entropy -> 64 hex chars. Unguessable.
SESSION_ID_BYTES = 32

_KEY_PREFIX = "session:"


def _key(session_id):
    return _KEY_PREFIX + session_id


async def mint(identity, email=None, name=None, picture=None,
               provider="google", now=None):
    """Issue a session for a verified identity. Update context only
    (raw_bytes is an inter-canister call). Returns (session_id, record)."""
    if not identity:
        raise ValueError("cannot mint a session without a verified identity")
    raw = await prandom.raw_bytes(SESSION_ID_BYTES)
    session_id = raw.hex()
    issued = ptime.now() if now is None else int(now)
    record = {
        "identity": identity,
        "email": email or "",
        "name": name or "",
        "picture": picture or "",
        "provider": provider,
        "created_at": issued,
        "expires_at": issued + SESSION_TTL_SECONDS,
    }
    kv.set(_key(session_id), record)
    return session_id, record


def get(session_id, now=None):
    """Query-fast validation: return the live session record, or None if the
    token is unknown or expired. Never writes (safe in query context)."""
    if not session_id:
        return None
    record = kv.get(_key(session_id))
    if record is None:
        return None
    current = ptime.now() if now is None else int(now)
    if current >= record["expires_at"]:
        return None  # expired — don't delete here (may be a query)
    return record


def revoke(session_id):
    """Invalidate a session (logout). Update context (writes kv)."""
    if session_id:
        kv.delete(_key(session_id))


def _token_from_request(req):
    """X-Session-Id (canonical) or Authorization: Bearer <session_id>."""
    sid = req.headers.get("x-session-id")
    if sid:
        return sid.strip()
    value = req.headers.get("authorization") or ""
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return None


def from_request(req, now=None):
    """(session_id, record|None) for the caller's session token, if any."""
    sid = _token_from_request(req)
    if not sid:
        return None, None
    return sid, get(sid, now=now)


def public_session(session_id, record):
    """Wire shape aligned with the frontend `Session` type
    (frontend/src/api/types.ts): identity is the flat provider `sub`."""
    return {
        "session_id": session_id,
        "identity": record["identity"],
        "email": record["email"],
        "name": record["name"],
        "picture": record["picture"],
    }
