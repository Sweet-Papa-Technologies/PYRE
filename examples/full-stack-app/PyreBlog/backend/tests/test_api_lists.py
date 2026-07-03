"""List endpoints: certified first page + live query variant."""

from conftest import api, body_json


def _publish(app, n, tags=None):
    for i in range(1, n + 1):
        resp = api(
            app, "POST", "/api/posts",
            body={
                "title": "Post %d" % i,
                "markdown": "body",
                "status": "published",
                "tags": tags or [],
            },
            auth=True,
        )
        assert resp.status == 201


def test_first_page_newest_first_published_only(app):
    _publish(app, 3)
    api(app, "POST", "/api/posts", body={"title": "Draft", "markdown": "d"}, auth=True)
    payload = body_json(api(app, "GET", "/api/posts"))
    assert [p["slug"] for p in payload["items"]] == ["post-3", "post-2", "post-1"]
    assert all("markdown" not in p for p in payload["items"])  # list is lean
    assert payload["next"] is None


def test_first_page_ignores_query_params_by_design(app):
    """/api/posts is the certified canonical page — params are not honored."""
    _publish(app, 2, tags=["icp"])
    unfiltered = body_json(api(app, "GET", "/api/posts", query="tag=nonexistent"))
    assert len(unfiltered["items"]) == 2  # filter deliberately not applied here


def test_query_variant_paginates(app):
    _publish(app, 5)
    p1 = body_json(api(app, "GET", "/api/posts/query", query="limit=2"))
    assert [p["slug"] for p in p1["items"]] == ["post-5", "post-4"]
    assert p1["next"]
    p2 = body_json(api(app, "GET", "/api/posts/query", query="limit=2&after=%s" % p1["next"]))
    assert [p["slug"] for p in p2["items"]] == ["post-3", "post-2"]
    p3 = body_json(api(app, "GET", "/api/posts/query", query="limit=2&after=%s" % p2["next"]))
    assert [p["slug"] for p in p3["items"]] == ["post-1"]
    assert p3["next"] is None


def test_query_variant_tag_filter(app):
    _publish(app, 1, tags=["icp"])
    api(
        app, "POST", "/api/posts",
        body={"title": "Other", "markdown": "m", "status": "published", "tags": ["misc"]},
        auth=True,
    )
    payload = body_json(api(app, "GET", "/api/posts/query", query="tag=icp"))
    assert [p["slug"] for p in payload["items"]] == ["post-1"]


def test_query_variant_bad_limit_400(app):
    resp = api(app, "GET", "/api/posts/query", query="limit=abc")
    assert resp.status == 400


def test_view_counts_appear_in_lists(app):
    _publish(app, 1)
    api(app, "POST", "/api/posts/post-1/view")
    payload = body_json(api(app, "GET", "/api/posts"))
    assert payload["items"][0]["views"] == 1
