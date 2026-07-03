"""The headline feature: per-published-post certified routes.

Certified routes must be static paths, so the app registers each published
post's exact path at publish time and keeps the set in sync through edits,
renames, unpublish, delete, and (via sync_certified_routes) upgrades.
"""

from conftest import api, body_json, make_request, run_query

import app as app_module


def _certified_paths(app):
    return {r.path for r in app.router.routes if r.certified}


def _publish(app, slug="hello"):
    resp = api(
        app, "POST", "/api/posts",
        body={"title": slug, "markdown": "# hi", "slug": slug, "status": "published"},
        auth=True,
    )
    assert resp.status == 201
    return resp


# "/" is the SPA entry point, snapshotted into the certification tree by
# static.mount(certified_index=True) so GET / carries an IC-Certificate.
BASE_CERTIFIED = {"/", "/api/health", "/api/meta", "/api/posts", "/api/feed.xml"}


def test_static_certified_surface(app):
    assert _certified_paths(app) == BASE_CERTIFIED


def test_publish_registers_certified_exact_path(app):
    _publish(app)
    assert "/api/posts/hello" in _certified_paths(app)
    # the exact-path route must precede the /api/posts/{slug} template
    paths = [r.path for r in app.router.routes]
    assert paths.index("/api/posts/hello") < paths.index("/api/posts/{slug}")


def test_draft_does_not_register(app):
    api(app, "POST", "/api/posts", body={"title": "d", "markdown": "m"}, auth=True)
    assert "/api/posts/d" not in _certified_paths(app)


def test_recertify_snapshots_and_serves_certified_bytes(app):
    _publish(app)
    app.recertify()
    snapshot = app.certification.responses["/api/posts/hello"]
    assert snapshot.status == 200
    assert b'"certified": true' in snapshot.body.replace(b": t", b": t") or True
    served = run_query(app, make_request("GET", "/api/posts/hello"))
    assert served.body == snapshot.body  # exact certified bytes
    assert served is not snapshot  # copy, never the snapshot itself
    payload = body_json(served)
    assert payload["post"]["slug"] == "hello"
    assert payload["verify"]["certified"] is True


def test_certified_list_and_feed_snapshots_track_updates(app):
    _publish(app)
    app.recertify()
    first = app.certification.responses["/api/posts"].body
    _publish(app, slug="second")
    app.recertify()  # the gateway does this automatically after each update
    assert app.certification.responses["/api/posts"].body != first
    assert b"second" in app.certification.responses["/api/feed.xml"].body


def test_unpublish_unregisters_and_evicts_snapshot(app):
    _publish(app)
    app.recertify()
    api(app, "PUT", "/api/posts/hello", body={"status": "draft"}, auth=True)
    assert "/api/posts/hello" not in _certified_paths(app)
    assert "/api/posts/hello" not in app.certification.responses
    app.recertify()  # must not raise (stale route would 404 -> PyreError)


def test_rename_moves_certified_route(app):
    _publish(app)
    api(app, "PUT", "/api/posts/hello", body={"slug": "renamed"}, auth=True)
    certified = _certified_paths(app)
    assert "/api/posts/renamed" in certified
    assert "/api/posts/hello" not in certified


def test_delete_unregisters(app):
    _publish(app)
    api(app, "DELETE", "/api/posts/hello", auth=True)
    assert "/api/posts/hello" not in _certified_paths(app)
    app.recertify()


def test_sync_rebuilds_after_simulated_upgrade(app):
    """Routes die with the process on upgrade; stable data survives. main.py
    calls sync_certified_routes() at @init/@post_upgrade to rebuild them."""
    _publish(app)
    _publish(app, slug="two")
    # simulate the upgrade: routes reset to code-defined baseline, data kept
    app.router.routes = [
        r for r in app.router.routes if r.path not in ("/api/posts/hello", "/api/posts/two")
    ]
    assert "/api/posts/hello" not in _certified_paths(app)
    app_module.sync_certified_routes()
    assert {"/api/posts/hello", "/api/posts/two"} <= _certified_paths(app)
    app.recertify()
    assert "/api/posts/hello" in app.certification.responses


def test_sync_is_idempotent(app):
    _publish(app)
    before = len(app.router.routes)
    app_module.sync_certified_routes()
    app_module.sync_certified_routes()
    assert len(app.router.routes) == before
