"""Route behavior: auth, validation, CRUD, drafts, view counter."""

from conftest import AUTH, api, body_json, make_request, run_query, run_update
from pyre.application import UPGRADE


def _create(app, auth=True, **fields):
    body = {"title": "T", "markdown": "hello **world**", "status": "published"}
    body.update(fields)
    return api(app, "POST", "/api/posts", body=body, auth=auth)


# --- auth ------------------------------------------------------------------------


def test_writes_require_token(app):
    resp = _create(app, auth=False)
    assert resp.status == 401
    assert ("www-authenticate", "Bearer") in resp.headers


def test_wrong_token_is_401(app):
    resp = api(
        app, "POST", "/api/posts",
        body={"title": "T", "markdown": "m"},
        headers={"authorization": "Bearer wrong-token"},
    )
    assert resp.status == 401


def test_reads_are_public(app):
    _create(app)
    assert body_json(api(app, "GET", "/api/posts"))["items"]
    assert api(app, "GET", "/api/health").status == 200


def test_delete_and_put_require_token(app):
    _create(app)
    assert api(app, "DELETE", "/api/posts/t").status == 401
    assert api(app, "PUT", "/api/posts/t", body={"title": "X"}).status == 401


# --- create ----------------------------------------------------------------------


def test_create_published_post(app):
    resp = _create(app, tags=["icp"])
    assert resp.status == 201
    payload = body_json(resp)
    post = payload["post"]
    assert post["slug"] == "t"  # derived from title
    assert "<strong>world</strong>" in post["html"]
    assert post["markdown"] == "hello **world**"
    assert post["tags"] == ["icp"]
    assert post["published_at"] > 0
    assert post["views"] == 0
    assert payload["verify"]["certified"] is True
    assert payload["verify"]["path"] == "/api/posts/t"


def test_create_validation_400_lists_fields(app):
    resp = api(app, "POST", "/api/posts", body={"markdown": 5}, auth=True)
    assert resp.status == 400
    fields = body_json(resp)["fields"]
    assert fields["title"] == "required field is missing"
    assert "expected str" in fields["markdown"]


def test_create_bad_status_400(app):
    resp = _create(app, status="scheduled")
    assert resp.status == 400


def test_create_invalid_slug_400(app):
    resp = _create(app, slug="Not A Slug")
    assert resp.status == 400
    assert body_json(resp)["error"] == "invalid slug"


def test_create_reserved_slug_400(app):
    resp = _create(app, slug="query")
    assert resp.status == 400


def test_slug_collision_409(app):
    assert _create(app).status == 201
    resp = _create(app)
    assert resp.status == 409
    assert body_json(resp)["error"] == "slug already exists"


# --- single read / drafts ------------------------------------------------------------


def test_get_published_post(app):
    _create(app)
    resp = api(app, "GET", "/api/posts/t")
    assert resp.status == 200
    assert body_json(resp)["post"]["slug"] == "t"


def test_unknown_slug_404(app):
    resp = api(app, "GET", "/api/posts/nope")
    assert resp.status == 404


def test_draft_hidden_without_token_visible_with(app):
    _create(app, status="draft")
    # anonymous: the query 404s -> gateway would upgrade -> update serves 404
    assert api(app, "GET", "/api/posts/t").status == 404
    # author preview with bearer token
    resp = run_query(app, make_request("GET", "/api/posts/t", headers=dict(AUTH)))
    assert resp is not UPGRADE and resp.status == 200
    payload = body_json(resp)
    assert payload["post"]["status"] == "draft"
    assert payload["verify"]["certified"] is False


# --- update -----------------------------------------------------------------------


def test_put_rerenders_markdown(app):
    _create(app)
    resp = api(app, "PUT", "/api/posts/t", body={"markdown": "# New"}, auth=True)
    assert resp.status == 200
    assert "<h1>New</h1>" in body_json(resp)["post"]["html"]


def test_put_unknown_fields_400(app):
    _create(app)
    resp = api(app, "PUT", "/api/posts/t", body={"nope": 1}, auth=True)
    assert resp.status == 400
    assert body_json(resp)["fields"] == ["nope"]


def test_put_rename_slug(app):
    _create(app)
    resp = api(app, "PUT", "/api/posts/t", body={"slug": "renamed"}, auth=True)
    assert resp.status == 200
    assert api(app, "GET", "/api/posts/renamed").status == 200
    assert api(app, "GET", "/api/posts/t").status == 404


def test_put_404_on_unknown(app):
    resp = api(app, "PUT", "/api/posts/none", body={"title": "X"}, auth=True)
    assert resp.status == 404


# --- delete ------------------------------------------------------------------------


def test_delete_then_404(app):
    _create(app)
    assert body_json(api(app, "DELETE", "/api/posts/t", auth=True)) == {"deleted": "t"}
    assert api(app, "GET", "/api/posts/t").status == 404
    assert api(app, "DELETE", "/api/posts/t", auth=True).status == 404


# --- view counter ---------------------------------------------------------------------


def test_view_counter_is_anonymous_and_increments(app):
    _create(app)
    assert body_json(api(app, "POST", "/api/posts/t/view"))["views"] == 1
    assert body_json(api(app, "POST", "/api/posts/t/view"))["views"] == 2
    assert body_json(api(app, "GET", "/api/posts/t"))["post"]["views"] == 2


def test_view_counter_404_for_unknown_or_draft(app):
    assert api(app, "POST", "/api/posts/nope/view").status == 404
    _create(app, status="draft")
    assert api(app, "POST", "/api/posts/t/view").status == 404


def test_view_counter_does_not_rewrite_post_doc(app):
    from pyrepress import posts as model

    _create(app)
    doc = model.get_by_slug("t")
    stored_before = model.posts.get(doc["id"])
    api(app, "POST", "/api/posts/t/view")
    assert model.posts.get(doc["id"]) == stored_before


# --- CORS -------------------------------------------------------------------------------


def test_cors_headers_and_preflight(app):
    resp = api(app, "GET", "/api/posts", headers={"origin": "http://localhost:5173"})
    assert ("access-control-allow-origin", "*") in resp.headers
    pre = run_query(
        app,
        make_request(
            "OPTIONS", "/api/posts",
            headers={"origin": "http://localhost:5173"},
        ),
    )
    assert pre.status == 204
    headers = dict(pre.headers)
    assert "POST" in headers["access-control-allow-methods"]
