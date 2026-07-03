"""The SPA is served from this canister (pyre.static). Two integration seams:

1. static.admin_routes upload POSTs must bypass the AUTHOR write-guard
   (_guard_writes) — they carry their own deploy-token guard. The author token
   must NOT be required to push the SPA.
2. static.mount registers a certified "/" index and a lower-priority catch-all;
   /api/* must still resolve to their handlers.
"""

from conftest import api, body_json, make_request, run_query

from pyrepress import config

DEPLOY = {"authorization": "Bearer %s" % config.STATIC_UPLOAD_TOKEN}
MANIFEST = {"assets": {"index.html": {"size": 3, "sha256": "a" * 64}}}


def test_upload_bypasses_author_guard_but_needs_deploy_token(app):
    # no token -> static's OWN guard 401s (NOT the author guard)
    assert api(app, "POST", "/_pyre/static/manifest", body=MANIFEST).status == 401
    # the AUTHOR token is the wrong credential here -> still 401 from static
    from conftest import AUTH
    assert api(app, "POST", "/_pyre/static/manifest", body=MANIFEST,
               headers=dict(AUTH)).status == 401
    # the deploy token passes the write-guard AND static's guard
    resp = api(app, "POST", "/_pyre/static/manifest", body=MANIFEST, headers=DEPLOY)
    assert resp.status == 200
    assert "index.html" in body_json(resp)["accepted"]


def test_api_routes_win_over_static_catchall(app):
    # health is a real API route, not swallowed by the SPA catch-all
    assert body_json(api(app, "GET", "/api/health"))["status"] == "ok"
    # an unknown /api path is a JSON 404, not the SPA index
    resp = api(app, "GET", "/api/does-not-exist")
    assert resp.status == 404


def test_spa_index_and_client_route_fallback(app):
    # "/" is the CERTIFIED index — a fast query serving the placeholder here
    # (no upload in this fresh-state test).
    root = run_query(app, make_request("GET", "/", headers={"accept": "text/html"}))
    assert root.status == 200
    assert b"<html" in root.body.lower()
    # The asset catch-all is flagged update=True (F16 workaround), so a query
    # to it returns the UPGRADE sentinel and the gateway re-issues it as an
    # update — api() replays that path. A client-side route (no dot, accepts
    # html) falls back to index.html.
    deep = api(app, "GET", "/post/some-slug", headers={"accept": "text/html"})
    assert deep.status == 200
    assert b"<html" in deep.body.lower()


def test_asset_catchall_is_update(app):
    """F16: the static asset catch-all must be an update route so it serves
    through the NORMAL (non-raw) gateway once certified routes exist."""
    catch = [r for r in app.router.routes if r.path.endswith("/{path:path}")]
    assert catch and all(r.update for r in catch)
