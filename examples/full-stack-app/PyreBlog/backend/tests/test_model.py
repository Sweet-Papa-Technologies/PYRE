"""Model layer: slugs, round-trips, views, newest-first listing."""

import pytest

from pyrepress import posts as model


# --- slug rules -------------------------------------------------------------------


def test_slugify_basic():
    assert model.slugify("Hello, World!") == "hello-world"
    assert model.slugify("PYRE v1.1: Python, verified") == "pyre-v1-1-python-verified"
    assert model.slugify("---") == "post"
    assert model.slugify("") == "post"


def test_slugify_truncates():
    assert len(model.slugify("x" * 500)) <= model.MAX_SLUG_LEN


@pytest.mark.parametrize("bad", ["Has Space", "UPPER", "-lead", "trail-", "a--b", "", "dots.dot"])
def test_check_slug_rejects(bad):
    with pytest.raises(model.SlugInvalid):
        model.check_slug(bad)


def test_check_slug_rejects_reserved():
    with pytest.raises(model.SlugInvalid):
        model.check_slug("query")


def test_check_slug_accepts():
    for ok in ("a", "a-b", "post-1", "x2-y3-z4"):
        model.check_slug(ok)  # must not raise


# --- round trips -------------------------------------------------------------------


def test_create_and_get_round_trip():
    doc = model.create_post("My Post", "# hi", tags=["t1"], status="published")
    fetched = model.get_by_slug("my-post")
    assert fetched == doc
    assert fetched["html"].startswith("<h1>")
    assert fetched["published_at"] > 0
    assert fetched["updated_at"] > 0
    assert fetched["status"] == "published"


def test_draft_has_no_published_at():
    doc = model.create_post("Draft", "body")
    assert doc["status"] == "draft"
    assert doc["published_at"] == 0


def test_duplicate_slug_raises():
    model.create_post("One", "a")
    with pytest.raises(model.SlugTaken):
        model.create_post("One", "b")


def test_update_rerenders_markdown_and_sets_updated_at():
    doc = model.create_post("P", "old")
    old, new = model.update_post("p", {"markdown": "**new**"})
    assert "<strong>new</strong>" in new["html"]
    assert new["updated_at"] >= old["updated_at"]


def test_first_publish_sets_published_at_once():
    model.create_post("P", "b")  # draft
    _, published = model.update_post("p", {"status": "published"})
    first_ts = published["published_at"]
    assert first_ts > 0
    _, republished = model.update_post("p", {"status": "draft"})
    _, again = model.update_post("p", {"status": "published"})
    assert again["published_at"] == first_ts  # not reset on re-publish


def test_rename_moves_slug_index():
    doc = model.create_post("P", "b")
    model.update_post("p", {"slug": "renamed"})
    assert model.get_by_slug("p") is None
    assert model.get_by_slug("renamed")["id"] == doc["id"]


def test_rename_to_taken_slug_raises():
    model.create_post("A", "a")
    model.create_post("B", "b")
    with pytest.raises(model.SlugTaken):
        model.update_post("a", {"slug": "b"})


def test_delete_removes_everything():
    doc = model.create_post("P", "b")
    model.incr_views(doc["id"])
    assert model.delete_post("p")["id"] == doc["id"]
    assert model.get_by_slug("p") is None
    assert model.views(doc["id"]) == 0  # counter gone too
    assert model.delete_post("p") is None


# --- views: hot writes never touch the post document --------------------------------


def test_views_live_outside_the_post_doc():
    doc = model.create_post("P", "b", status="published")
    stored_before = model.posts.get(doc["id"])
    assert model.incr_views(doc["id"]) == 1
    assert model.incr_views(doc["id"]) == 2
    assert model.views(doc["id"]) == 2
    assert model.posts.get(doc["id"]) == stored_before  # doc bytes unchanged
    assert "views" not in model.posts.get(doc["id"])
    assert model.public_post(doc)["views"] == 2  # merged into the wire shape


# --- listing --------------------------------------------------------------------------


def _make_posts(n, status="published", tags=None):
    return [
        model.create_post("Post %d" % i, "body %d" % i, tags=tags or [], status=status)
        for i in range(1, n + 1)
    ]


def test_list_newest_first_and_published_only():
    _make_posts(3)
    model.create_post("Hidden draft", "d")  # draft
    page = model.list_published(limit=10)
    slugs = [d["slug"] for d in page["items"]]
    assert slugs == ["post-3", "post-2", "post-1"]  # ties broken by id desc
    assert page["next"] is None


def test_list_pagination_cursor():
    _make_posts(5)
    p1 = model.list_published(limit=2)
    assert [d["slug"] for d in p1["items"]] == ["post-5", "post-4"]
    assert p1["next"] == p1["items"][-1]["id"]
    p2 = model.list_published(limit=2, after=p1["next"])
    assert [d["slug"] for d in p2["items"]] == ["post-3", "post-2"]
    p3 = model.list_published(limit=2, after=p2["next"])
    assert [d["slug"] for d in p3["items"]] == ["post-1"]
    assert p3["next"] is None


def test_list_unknown_cursor_gives_empty_page():
    _make_posts(2)
    page = model.list_published(limit=2, after="nonsense")
    assert page == {"items": [], "next": None}


def test_list_tag_filter_is_membership():
    model.create_post("A", "a", tags=["icp", "pyre"], status="published")
    model.create_post("B", "b", tags=["other"], status="published")
    page = model.list_published(tag="icp")
    assert [d["slug"] for d in page["items"]] == ["a"]
