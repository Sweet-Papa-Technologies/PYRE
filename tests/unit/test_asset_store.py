import hashlib

import pytest

from pyre import kv
from pyre._asset_store import AssetConflict, AssetQuotaExceeded, ChunkStore


def setup_function():
    kv._backend = kv._DevBackend(); kv.ctx.in_query = False


def upload(store, name, body, session="upload"):
    state = store.begin(name, size=len(body), sha256=hashlib.sha256(body).hexdigest(), session_id=session)
    for index in range(state["chunks"]):
        piece = body[index * store.chunk_size:(index + 1) * store.chunk_size]
        store.put_chunk(session, index, piece)
    return store.finalize(session)


def test_resumable_idempotent_chunks_and_verified_finalization():
    store = ChunkStore("media", chunk_size=1024)
    body = b"a" * 2500
    state = store.begin("movie.mp4", size=len(body), sha256=hashlib.sha256(body).hexdigest(), session_id="s1")
    assert store.put_chunk("s1", 0, body[:1024]) is False
    assert store.put_chunk("s1", 0, body[:1024]) is True
    with pytest.raises(AssetConflict):
        store.put_chunk("s1", 0, b"b" * 1024)
    store.put_chunk("s1", 1, body[1024:2048]); store.put_chunk("s1", 2, body[2048:])
    manifest = store.finalize("s1")
    assert store.read("movie.mp4") == body
    assert store.finalize("s1") == manifest


def test_hash_failure_never_publishes_and_quotas_apply():
    store = ChunkStore("small", max_asset_bytes=1500, max_total_bytes=1800, chunk_size=1024)
    with pytest.raises(AssetQuotaExceeded):
        store.begin("large", size=1501, sha256="0" * 64)
    upload(store, "one", b"x" * 1200, "one")
    with pytest.raises(AssetQuotaExceeded):
        store.begin("two", size=700, sha256=hashlib.sha256(b"y" * 700).hexdigest(), session_id="two")
    bad = store.begin("bad", size=2, sha256=hashlib.sha256(b"ok").hexdigest(), session_id="bad")
    store.put_chunk("bad", 0, b"no")
    with pytest.raises(AssetConflict):
        store.finalize("bad")


def test_manifest_rejects_unbounded_chunk_count_before_writes():
    store = ChunkStore("bounded", chunk_size=1024)
    size = 513 * 1024
    with pytest.raises(AssetQuotaExceeded, match="safe finalization limit"):
        store.begin("too-many", size=size, sha256=hashlib.sha256(b"x").hexdigest())


def test_token_is_compact_strict_and_generation_bound():
    store = ChunkStore("media", chunk_size=1024)
    manifest = upload(store, "asset", b"x" * 1200)
    token = store.token("asset", manifest["generation"], 1)
    assert len(token) < 512
    assert store.decode_token(token)["i"] == 1
    with pytest.raises(Exception, match="invalid streaming token"):
        store.decode_token("not-json")


def test_bounded_delete_removes_live_pointer_then_resumes():
    store = ChunkStore("media", chunk_size=1024)
    upload(store, "large", b"z" * 3500)
    first = store.delete("large", limit=2)
    assert first == {"asset_id": "large", "removed_chunks": 2,
                     "remaining_chunks": 2, "complete": False}
    with pytest.raises(Exception, match="not found"):
        store.get_manifest("large")
    assert store.garbage_collect(limit=1)[0]["remaining_chunks"] == 1
    assert store.garbage_collect(limit=10)[0]["complete"] is True
    assert store.list_assets() == []


def test_namespace_and_global_quotas_are_distinct():
    first = ChunkStore("one", max_namespace_bytes=1500, max_total_bytes=2000, chunk_size=1024)
    upload(first, "a", b"a" * 1200, "a")
    second = ChunkStore("two", max_namespace_bytes=1500, max_total_bytes=2000, chunk_size=1024)
    with pytest.raises(AssetQuotaExceeded, match="global"):
        second.begin("b", size=900, sha256=hashlib.sha256(b"b" * 900).hexdigest())


def test_replacement_queues_old_generation_for_bounded_gc():
    store = ChunkStore("media", chunk_size=1024)
    old = upload(store, "asset", b"a" * 2200, "old")
    new = upload(store, "asset", b"b" * 1100, "new")
    assert new["generation"] != old["generation"]
    result = store.garbage_collect(limit=1)[0]
    assert result["generation"] == old["generation"] and result["complete"] is False
    while not store.garbage_collect(limit=10)[0]["complete"]:
        pass


def test_republished_generation_is_not_destroyed_by_gc():
    # regression: A->B->A re-publishes A's deterministic generation while a
    # stale garbage tombstone for A (queued during A->B) still exists; GC then
    # deleted the now-live chunks. finalize must clear that tombstone.
    store = ChunkStore("media", chunk_size=1024)
    body_a = b"A" * 1500
    upload(store, "asset", body_a, "sa")
    upload(store, "asset", b"B" * 1500, "sb")
    upload(store, "asset", body_a, "sa2")  # re-publish A (identical content)
    store.garbage_collect(limit=1000)
    assert store.read("asset") == body_a


def test_identical_content_can_be_reuploaded_after_delete():
    # regression: the finalized upload session persisted after delete, so
    # re-uploading identical bytes hit "upload session is finalized".
    store = ChunkStore("media", chunk_size=1024)
    body = b"v" * 500
    upload(store, "note", body, "s1")
    while not store.delete("note")["complete"]:
        pass
    upload(store, "note", body, "s1")
    assert store.read("note") == body
