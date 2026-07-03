"""Integration-drift routes: the author admin surface the SPA calls.

GET  /api/admin/posts        list ALL posts incl. drafts (AdminPostList)
GET  /api/admin/posts/{slug} any post incl. draft, full fidelity (AdminPost)
POST /api/posts/{slug}/publish  publish a draft, return the AdminPost

All are author-only. The two GETs are update=True (F16 workaround), which the
`api()` helper transparently re-issues as an update when a query returns the
UPGRADE sentinel.
"""

from conftest import AUTH, api, body_json, make_request, run_query


def _create(app, **fields):
    body = {"title": "T", "markdown": "hello **world**", "status": "draft"}
    body.update(fields)
    return api(app, "POST", "/api/posts", body=body, auth=True)


# --- admin list ------------------------------------------------------------------


def test_admin_list_requires_token(app):
    _create(app)
    resp = api(app, "GET", "/api/admin/posts")
    assert resp.status == 401
    assert ("www-authenticate", "Bearer") in resp.headers


def test_admin_list_includes_drafts_newest_first(app):
    _create(app, title="Draft One", slug="draft-one", status="draft")
    _create(app, title="Pub Two", slug="pub-two", status="published")
    resp = api(app, "GET", "/api/admin/posts", auth=True)
    assert resp.status == 200
    payload = body_json(resp)
    slugs = [p["slug"] for p in payload["items"]]
    # both statuses present (drafts are NOT hidden from the author)
    assert set(slugs) == {"draft-one", "pub-two"}
    assert payload["total"] == 2
    # newest-touched first: pub-two was created after draft-one
    assert slugs[0] == "pub-two"
    # AdminPost shape carries the full-fidelity fields
    post = payload["items"][0]
    for key in ("id", "slug", "title", "markdown", "html", "tags", "status",
                "published_at", "updated_at", "views", "schema_version", "url"):
        assert key in post, key
    assert post["url"] == "/post/pub-two"


# --- admin get -------------------------------------------------------------------


def test_admin_get_draft_requires_token(app):
    _create(app, slug="secret", status="draft")
    assert api(app, "GET", "/api/admin/posts/secret").status == 401
    resp = api(app, "GET", "/api/admin/posts/secret", auth=True)
    assert resp.status == 200
    post = body_json(resp)
    assert post["slug"] == "secret"
    assert post["status"] == "draft"
    assert post["markdown"] == "hello **world**"
    assert "<strong>world</strong>" in post["html"]


def test_admin_get_unknown_404(app):
    assert api(app, "GET", "/api/admin/posts/nope", auth=True).status == 404


# --- publish ---------------------------------------------------------------------


def test_publish_requires_token(app):
    _create(app, slug="p", status="draft")
    assert api(app, "POST", "/api/posts/p/publish").status == 401


def test_publish_sets_status_and_published_at(app):
    _create(app, slug="p", status="draft")
    resp = api(app, "POST", "/api/posts/p/publish", auth=True)
    assert resp.status == 200
    post = body_json(resp)
    assert post["status"] == "published"
    assert post["published_at"] > 0
    assert post["url"] == "/post/p"
    # now publicly readable and served from the certified exact route
    assert api(app, "GET", "/api/posts/p").status == 200


def test_publish_registers_certified_route(app):
    import app as app_module

    _create(app, slug="p", status="draft")
    assert "/api/posts/p" not in {r.path for r in app.router.routes if r.certified}
    api(app, "POST", "/api/posts/p/publish", auth=True)
    assert "/api/posts/p" in {r.path for r in app_module.app.router.routes if r.certified}


def test_publish_unknown_404(app):
    assert api(app, "POST", "/api/posts/none/publish", auth=True).status == 404
