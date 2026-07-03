"""Phase C: sessions, OIDC login (MOCKED verifier), comments, moderation.

OIDC signature verification is mocked here (a test provider that maps a known
token -> known claims) so the SESSION / COMMENT / MODERATION logic — rate
limits, size caps, expiry, pending->approved flow, certified approved list —
is proven on host without a native RSA build. The REAL in-canister RS256/ES256
verify path is proven separately by examples/oidc_spike (Phase-B gate: PASS).
"""

import pytest

from conftest import AUTH, api, body_json, make_request, run_query, run_update
from pyre.application import UPGRADE

import app as app_module
from pyrepress import comments as comment_model
from pyrepress import sessions

GOOGLE_SUB = "google-sub-123"
GOOGLE_CLAIMS = {
    "sub": GOOGLE_SUB,
    "email": "reader@example.com",
    "email_verified": True,
    "name": "Ada Reader",
    "picture": "https://example.com/ada.png",
}
GOOD_TOKEN = "valid-google-id-token"


class MockVerifier:
    """Stands in for oidc.OidcVerifier: token -> claims, else raise."""

    def __init__(self, tokens):
        self.tokens = tokens

    async def verify(self, id_token):
        from pyre import oidc

        claims = self.tokens.get(id_token)
        if claims is None:
            raise oidc.InvalidSignature("mock: unknown token")
        return claims


@pytest.fixture(autouse=True)
def mock_oidc():
    app_module.oidc_verifiers.clear()
    app_module.oidc_verifiers["google"] = MockVerifier({GOOD_TOKEN: GOOGLE_CLAIMS})
    yield
    app_module.oidc_verifiers.clear()


# --- helpers -----------------------------------------------------------------


def run_async(coro):
    """Drive a coroutine that makes no real outcalls (host raw_bytes/os.urandom)."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("coroutine yielded a future; none expected on host")


def login(app, token=GOOD_TOKEN, provider="google"):
    return api(app, "POST", "/api/auth/login", body={"provider": provider, "token": token})


def publish(app, slug="t"):
    return api(app, "POST", "/api/posts",
               body={"title": slug, "slug": slug, "markdown": "hi", "status": "published"},
               auth=True)


def session_headers(sid):
    return {"x-session-id": sid}


# --- sessions module ---------------------------------------------------------


def test_session_mint_get_and_expiry(app):
    sid, record = run_async(sessions.mint(GOOGLE_SUB, email="a@b.c", name="Ada"))
    assert len(sid) == 64  # 32 bytes hex
    assert sessions.get(sid)["identity"] == GOOGLE_SUB
    # expired lookups fail without mutating
    future = record["expires_at"] + 1
    assert sessions.get(sid, now=future) is None
    assert sessions.get(sid) is not None  # still there (query never deleted it)


def test_session_revoke(app):
    sid, _ = run_async(sessions.mint(GOOGLE_SUB))
    sessions.revoke(sid)
    assert sessions.get(sid) is None


def test_session_from_request_bearer_fallback(app):
    sid, _ = run_async(sessions.mint(GOOGLE_SUB))
    req = make_request("GET", "/x", headers={"authorization": "Bearer %s" % sid})
    got_sid, rec = sessions.from_request(req)
    assert got_sid == sid and rec["identity"] == GOOGLE_SUB


# --- auth routes -------------------------------------------------------------


def test_login_success_returns_session(app):
    resp = login(app)
    assert resp.status == 200
    data = body_json(resp)
    assert len(data["session_id"]) == 64
    assert data["identity"] == GOOGLE_SUB
    assert data["email"] == "reader@example.com"
    assert data["name"] == "Ada Reader"


def test_login_bad_token_401(app):
    resp = login(app, token="forged")
    assert resp.status == 401


def test_login_unknown_provider_400(app):
    resp = api(app, "POST", "/api/auth/login", body={"provider": "myspace", "token": GOOD_TOKEN})
    assert resp.status == 400


def test_google_alias_accepts_id_token(app):
    resp = api(app, "POST", "/api/auth/google", body={"id_token": GOOD_TOKEN})
    assert resp.status == 200
    assert body_json(resp)["identity"] == GOOGLE_SUB


def test_auth_me_requires_session(app):
    assert api(app, "GET", "/api/auth/me").status == 401
    sid = body_json(login(app))["session_id"]
    resp = run_query(app, make_request("GET", "/api/auth/me", headers=session_headers(sid)))
    assert resp is not UPGRADE and resp.status == 200
    assert body_json(resp)["identity"] == GOOGLE_SUB


def test_logout_invalidates_session(app):
    sid = body_json(login(app))["session_id"]
    assert api(app, "POST", "/api/auth/logout", headers=session_headers(sid)).status == 200
    assert api(app, "GET", "/api/auth/me", headers=session_headers(sid)).status == 401


# --- comment submit ----------------------------------------------------------


def test_submit_requires_session_401(app):
    publish(app)
    resp = api(app, "POST", "/api/posts/t/comments", body={"body": "hi"})
    assert resp.status == 401


def test_submit_authenticated_is_pending(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    resp = api(app, "POST", "/api/posts/t/comments", body={"body": "great post"},
               headers=session_headers(sid))
    assert resp.status == 201
    comment = body_json(resp)
    assert comment["status"] == "pending"
    assert comment["author_identity"] == GOOGLE_SUB
    assert comment["body"] == "great post"
    assert "author_email" not in comment  # email not leaked publicly


def test_submit_unknown_or_draft_slug_404(app):
    sid = body_json(login(app))["session_id"]
    assert api(app, "POST", "/api/posts/nope/comments", body={"body": "x"},
               headers=session_headers(sid)).status == 404
    api(app, "POST", "/api/posts",
        body={"title": "d", "slug": "d", "markdown": "m", "status": "draft"}, auth=True)
    assert api(app, "POST", "/api/posts/d/comments", body={"body": "x"},
               headers=session_headers(sid)).status == 404


def test_submit_oversized_body_413(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    big = "x" * (comment_model.MAX_BODY_CHARS + 1)
    resp = api(app, "POST", "/api/posts/t/comments", body={"body": big},
               headers=session_headers(sid))
    assert resp.status == 413


def test_submit_empty_body_400(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    assert api(app, "POST", "/api/posts/t/comments", body={"body": "   "},
               headers=session_headers(sid)).status == 400


def test_rate_limit_pending_backlog_429(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    for _ in range(comment_model.MAX_PENDING_PER_AUTHOR):
        assert api(app, "POST", "/api/posts/t/comments", body={"body": "ok"},
                   headers=session_headers(sid)).status == 201
    resp = api(app, "POST", "/api/posts/t/comments", body={"body": "one too many"},
               headers=session_headers(sid))
    assert resp.status == 429


# --- certified approved list + moderation ------------------------------------


def _submit(app, sid, slug="t", body="hello"):
    return body_json(api(app, "POST", "/api/posts/%s/comments" % slug,
                         body={"body": body}, headers=session_headers(sid)))


def test_pending_hidden_until_approved_then_certified(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    cid = _submit(app, sid, body="approve me")["id"]

    # pending -> not in the public approved list
    assert body_json(api(app, "GET", "/api/posts/t/comments"))["items"] == []

    # author approves (bearer)
    resp = api(app, "POST", "/api/comments/%s/approve" % cid, auth=True)
    assert resp.status == 200
    items = body_json(api(app, "GET", "/api/posts/t/comments"))["items"]
    assert [c["body"] for c in items] == ["approve me"]
    assert items[0]["status"] == "approved"


def test_reject_stays_hidden(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    cid = _submit(app, sid, body="spam")["id"]
    assert api(app, "POST", "/api/comments/%s/reject" % cid, auth=True).status == 200
    assert body_json(api(app, "GET", "/api/posts/t/comments"))["items"] == []


def test_moderation_queue_requires_bearer(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    _submit(app, sid)
    assert api(app, "GET", "/api/comments/pending").status == 401
    resp = api(app, "GET", "/api/comments/pending", auth=True)
    assert resp.status == 200
    assert len(body_json(resp)["items"]) == 1


def test_moderation_alias_status_filter(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    cid = _submit(app, sid)["id"]
    api(app, "POST", "/api/comments/%s/approve" % cid, auth=True)
    approved = body_json(api(app, "GET", "/api/moderation/comments",
                             query="status=approved", auth=True))
    assert len(approved["items"]) == 1
    pending = body_json(api(app, "GET", "/api/moderation/comments",
                            query="status=pending", auth=True))
    assert pending["items"] == []


def test_approve_unknown_comment_404(app):
    assert api(app, "POST", "/api/comments/000000000999/approve", auth=True).status == 404


def test_upgrade_survival_sessions_and_comments(app):
    """Dynamic routes die on upgrade; stable kv/data survive. main.py rebuilds
    the certified routes at @post_upgrade via sync_certified_routes()."""
    publish(app, "up")
    sid = body_json(login(app))["session_id"]
    cid = _submit(app, sid, slug="up", body="survivor")["id"]
    api(app, "POST", "/api/comments/%s/approve" % cid, auth=True)

    # simulate the upgrade: drop the dynamic per-post routes, keep stable data
    app_module.app.router.routes = [
        r for r in app_module.app.router.routes
        if not (r.certified and r.path.startswith("/api/posts/up"))
    ]
    app_module.sync_certified_routes()

    # session survives (kv) …
    assert sessions.get(sid) is not None
    # … and the approved comment survives + its certified route is rebuilt
    items = body_json(api(app, "GET", "/api/posts/up/comments"))["items"]
    assert [c["body"] for c in items] == ["survivor"]
    certified = {r.path for r in app_module.app.router.routes if r.certified}
    assert "/api/posts/up/comments" in certified


def test_moderation_frees_pending_rate_budget(app):
    publish(app)
    sid = body_json(login(app))["session_id"]
    ids = [_submit(app, sid, body="c%d" % i)["id"]
           for i in range(comment_model.MAX_PENDING_PER_AUTHOR)]
    # at the cap now
    assert api(app, "POST", "/api/posts/t/comments", body={"body": "x"},
               headers=session_headers(sid)).status == 429
    # approving one frees a slot
    api(app, "POST", "/api/comments/%s/approve" % ids[0], auth=True)
    assert api(app, "POST", "/api/posts/t/comments", body={"body": "now ok"},
               headers=session_headers(sid)).status == 201
