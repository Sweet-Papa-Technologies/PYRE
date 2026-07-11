import hashlib

from pyre import App, kv
from pyre.assets import AssetStore, admin_routes, streaming_callback
from pyre.http_types import Request
from pyre.testing import PyreTestClient


def setup_function():
    kv._backend = kv._DevBackend(); kv.ctx.in_query = False


def stored(body):
    store = AssetStore("media", chunk_size=45_000 if len(body) > 512 * 1024 else 1024)
    state = store.begin("video", size=len(body), sha256=hashlib.sha256(body).hexdigest(), content_type="video/mp4")
    for index in range(state["chunks"]):
        store.put_chunk(state["session_id"], index,
                        body[index * store.chunk_size:(index + 1) * store.chunk_size])
    store.finalize(state["session_id"])
    return store


def test_large_response_streams_one_chunk_at_a_time():
    body = bytes(range(256)) * 12
    response = stored(body).response("video", request=Request("GET", "/video"))
    assert response.status == 200 and len(response.body) == 1024
    parts = [response.body]
    token = response.streaming_token
    while token:
        result = streaming_callback(token)
        parts.append(result["body"])
        token_record = result["token"]
        token = token_record["arbitrary_data"] if token_record else None
    assert b"".join(parts) == body


def test_single_range_and_invalid_multiple_range():
    store = stored(b"0123456789" * 200)
    request = Request("GET", "/video", headers={"range": "bytes=10-19"})
    response = store.response("video", request=request)
    assert response.status == 206 and response.body == b"0123456789"
    invalid = store.response("video", request=Request("GET", "/video", headers={"range": "bytes=0-1,4-5"}))
    assert invalid.status == 416


def test_large_range_streams_without_reassembling_asset():
    body = bytes(range(251)) * 20
    store = stored(body)
    response = store.response("video", request=Request("GET", "/video", headers={"range": "bytes=500-4099"}))
    assert response.status == 206 and len(response.body) <= store.chunk_size
    parts, token = [response.body], response.streaming_token
    while token:
        result = streaming_callback(token); parts.append(result["body"])
        token = result["token"]["arbitrary_data"] if result["token"] else None
    assert b"".join(parts) == body[500:4100]


def test_asset_over_1_8_mb_streams_in_bounded_chunks():
    body = (b"large-asset-check-" * 110_000)[:1_900_001]
    store = stored(body)
    response = store.response("video", request=Request("GET", "/video"))
    count, total, token = 1, len(response.body), response.streaming_token
    assert len(response.body) <= store.chunk_size and token is not None
    while token:
        result = streaming_callback(token)
        assert len(result["body"]) <= store.chunk_size
        total += len(result["body"]); count += 1
        token = result["token"]["arbitrary_data"] if result["token"] else None
    assert total == len(body) and count > 40


def test_content_type_header_injection_rejected():
    store = AssetStore("media", chunk_size=1024)
    try:
        store.begin("bad", size=0, sha256=hashlib.sha256(b"").hexdigest(), content_type="text/plain\r\nx: y")
    except ValueError as exc:
        assert "content type" in str(exc)
    else:
        raise AssertionError("header injection was accepted")


def test_authenticated_management_routes_list_verify_and_delete():
    store = stored(b"hello" * 300)
    app = App(); admin_routes(app, store, "secret")
    client = PyreTestClient.from_app(app)
    assert client.get("/_pyre/assets/list").status_code == 401
    headers = {"authorization": "Bearer secret"}
    listing = client.get("/_pyre/assets/list", headers=headers).json()
    assert listing["assets"][0]["asset_id"] == "video"
    verified = client.post("/_pyre/assets/verify", headers=headers,
                           json_body={"asset_id": "video"}).json()
    assert verified["ok"] is True
    progress = client.post("/_pyre/assets/delete", headers=headers,
                           json_body={"asset_id": "video", "limit": 1}).json()
    assert progress["removed_chunks"] == 1 and progress["complete"] is False


def test_generalized_upload_routes_are_resumable_and_finalize():
    import base64, hashlib
    store = AssetStore("uploads", chunk_size=1024)
    app = App(); admin_routes(app, store, "secret")
    client = PyreTestClient.from_app(app); headers = {"authorization": "Bearer secret"}
    body = b"abc" * 500
    manifest = {"asset_id": "clip", "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(), "content_type": "video/mp4"}
    started = client.post("/_pyre/assets/manifest", headers=headers, json_body=manifest).json()
    session = started["session"]
    for index in range(session["chunks"]):
        piece = body[index * 1024:(index + 1) * 1024]
        payload = {"session_id": session["session_id"], "index": index,
                   "data": base64.b64encode(piece).decode()}
        assert client.post("/_pyre/assets/chunk", headers=headers, json_body=payload).status_code == 200
    resumed = client.post("/_pyre/assets/manifest", headers=headers, json_body=manifest).json()
    assert resumed["present"] == list(range(session["chunks"]))
    finalized = client.post("/_pyre/assets/finalize", headers=headers,
                            json_body={"session_id": session["session_id"]}).json()
    assert finalized["asset"]["sha256"] == manifest["sha256"]
    assert store.read("clip") == body


def _finalize_at(namespace, asset_id, body, chunk_size):
    store = AssetStore(namespace, chunk_size=chunk_size)
    state = store.begin(asset_id, size=len(body), sha256=hashlib.sha256(body).hexdigest(),
                        content_type="application/octet-stream")
    for index in range(state["chunks"]):
        store.put_chunk(state["session_id"], index, body[index * chunk_size:(index + 1) * chunk_size])
    store.finalize(state["session_id"])
    return store


def test_range_indexes_by_manifest_chunk_size_not_store_config():
    # regression: response() indexed chunks by the live store's chunk_size, so a
    # store rebuilt with a different chunk_size served corrupted bytes.
    body = bytes(range(256)) * 20  # 5120 bytes
    _finalize_at("media", "f", body, 1024)
    serving = AssetStore("media", chunk_size=2048)  # different config, same data
    response = serving.response("f", request=Request("GET", "/f", headers={"range": "bytes=3000-3100"}))
    assert response.status == 206
    assert bytes(response.body) == body[3000:3072]  # first chunk's slice, correct bytes


def test_range_end_past_eof_is_clamped_not_416():
    # regression: a concrete last-byte-pos >= size returned 416; RFC 7233 clamps.
    store = _finalize_at("clips", "v", b"x" * 2000, 1024)
    response = store.response("v", request=Request("GET", "/v", headers={"range": "bytes=0-99999"}))
    assert response.status == 206
    parts, token = [response.body], response.streaming_token
    while token:
        result = streaming_callback(token); parts.append(result["body"])
        token = result["token"]["arbitrary_data"] if result["token"] else None
    assert b"".join(parts) == b"x" * 2000
