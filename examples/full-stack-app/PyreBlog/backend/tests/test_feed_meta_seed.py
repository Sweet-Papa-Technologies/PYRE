"""RSS feed shape, meta config, token rotation, seed content."""

from conftest import api, body_json

from pyrepress import config, feed


# --- RSS ---------------------------------------------------------------------------


def _publish(app, title, slug, markdown="body"):
    resp = api(
        app, "POST", "/api/posts",
        body={"title": title, "markdown": markdown, "slug": slug, "status": "published"},
        auth=True,
    )
    assert resp.status == 201


def test_feed_is_rss2_with_correct_content_type(app):
    _publish(app, "First", "first")
    resp = api(app, "GET", "/api/feed.xml")
    assert resp.status == 200
    assert dict(resp.headers)["content-type"].startswith("application/rss+xml")
    xml = resp.body.decode()
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<rss version="2.0">' in xml
    assert "<channel>" in xml
    assert "<item>" in xml
    assert "<guid" in xml and "<pubDate>" in xml


def test_feed_escapes_content(app):
    _publish(app, "Tom & Jerry <3", "tom-jerry", markdown="a & b")
    xml = api(app, "GET", "/api/feed.xml").body.decode()
    assert "Tom &amp; Jerry &lt;3" in xml
    assert "Tom & Jerry" not in xml
    # rendered html inside <description> is escaped, not raw
    assert "<description>&lt;p&gt;" in xml


def test_feed_caps_at_20_and_newest_first(app):
    for i in range(1, 24):
        _publish(app, "P%d" % i, "p-%d" % i)
    xml = api(app, "GET", "/api/feed.xml").body.decode()
    assert xml.count("<item>") == 20
    assert xml.index("<title>P23</title>") < xml.index("<title>P22</title>")
    assert "<title>P1</title>" not in xml  # oldest fell off


def test_feed_excludes_drafts(app):
    api(app, "POST", "/api/posts", body={"title": "Secret", "markdown": "m"}, auth=True)
    xml = api(app, "GET", "/api/feed.xml").body.decode()
    assert "Secret" not in xml


def test_rfc822_format():
    assert feed.rfc822(0) == "Thu, 01 Jan 1970 00:00:00 GMT"
    assert feed.rfc822(1783024113) == "Thu, 02 Jul 2026 20:28:33 GMT"


# --- meta ---------------------------------------------------------------------------


def test_meta_defaults(app):
    meta = body_json(api(app, "GET", "/api/meta"))
    assert meta["title"] == config.DEFAULT_META["title"]


def test_put_meta_requires_token_and_merges(app):
    assert api(app, "PUT", "/api/meta", body={"title": "X"}).status == 401
    resp = api(app, "PUT", "/api/meta", body={"title": "My Blog"}, auth=True)
    assert resp.status == 200
    meta = body_json(api(app, "GET", "/api/meta"))
    assert meta["title"] == "My Blog"
    assert meta["author"] == config.DEFAULT_META["author"]  # untouched fields kept


def test_token_rotation(app):
    resp = api(app, "PUT", "/api/meta", body={"token": "brand-new-secret"}, auth=True)
    assert resp.status == 200
    assert "token" not in body_json(resp)  # never echoed
    # old token now rejected
    assert api(app, "PUT", "/api/meta", body={"title": "x"}, auth=True).status == 401
    # new token accepted
    ok = api(
        app, "PUT", "/api/meta", body={"title": "x"},
        headers={"authorization": "Bearer brand-new-secret"},
    )
    assert ok.status == 200
    import pyre.kv as kv_module

    assert "brand-new-secret" not in str(kv_module._backend._store)  # only the hash


# --- seed ----------------------------------------------------------------------------


def test_seed_loads_demo_posts_idempotently(app):
    resp = api(app, "POST", "/api/seed", auth=True)
    created = body_json(resp)["created"]
    assert "pyre-v1-1-announcement" in created
    assert len(created) == 4
    # announcement is published + certified
    payload = body_json(api(app, "GET", "/api/posts/pyre-v1-1-announcement"))
    assert payload["verify"]["certified"] is True
    assert "Internet Computer" in payload["post"]["html"]
    # draft seed stays hidden
    assert api(app, "GET", "/api/posts/roadmap-notes").status == 404
    # idempotent
    again = body_json(api(app, "POST", "/api/seed", auth=True))
    assert again["created"] == []


def test_seed_requires_token(app):
    assert api(app, "POST", "/api/seed").status == 401
