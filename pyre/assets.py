"""Generalized public asset storage and HTTP streaming responses."""

import base64

from pyre import kv
from pyre._asset_store import ChunkStore, AssetNotFound, AssetStoreError
from pyre.http_types import Response

try:
    from hmac import compare_digest
except ImportError:  # pragma: no cover
    compare_digest = lambda a, b: a == b


class AssetStore(ChunkStore):
    def response(self, asset_id, request=None, stream=True):
        manifest = self.get_manifest(asset_id)
        start, end = 0, manifest["size"] - 1
        status, headers = 200, [("content-type", manifest["content_type"]), ("accept-ranges", "bytes")]
        if manifest["size"] == 0:
            headers.append(("content-length", "0"))
            return Response(b"", status=200, headers=headers)
        range_value = request.headers.get("range") if request is not None else None
        if range_value:
            try:
                unit, value = range_value.split("=", 1)
                if unit != "bytes" or "," in value: raise ValueError()
                left, right = value.split("-", 1)
                if not left: start = max(0, manifest["size"] - int(right))
                else: start = int(left)
                if right and left: end = int(right)
                if start < 0 or end < start or end >= manifest["size"]: raise ValueError()
            except (ValueError, TypeError):
                return Response(b"", status=416, headers=[("content-range", "bytes */%d" % manifest["size"])])
            status = 206; headers.append(("content-range", "bytes %d-%d/%d" % (start, end, manifest["size"])))
        first_index = start // self.chunk_size
        first, _ = self.read_chunk(asset_id, manifest["generation"], first_index)
        first_start = start - first_index * self.chunk_size
        first_end = min(len(first), end - first_index * self.chunk_size + 1)
        first = first[first_start:first_end]
        token = None
        last_index = end // self.chunk_size
        if stream and first_index < last_index:
            token = self.token(asset_id, manifest["generation"], first_index + 1,
                               start=start, end=end)
        elif not stream:
            # Explicit non-streaming is capped to one safe chunk. Callers must
            # opt into streaming for larger bodies rather than trigger a large
            # in-message allocation.
            if first_index < last_index:
                raise AssetStoreError("response spans multiple chunks; stream=True is required")
        headers.append(("content-length", str(end - start + 1)))
        return Response(first, status=status, headers=headers, streaming_token=token)


def streaming_callback(token):
    """Pure query callback body: returns one chunk and an optional next token."""
    payload = ChunkStore.decode_token(token)
    store = AssetStore(payload["n"], chunk_size=payload["c"])
    body, manifest = store.read_chunk(payload["a"], payload["g"], payload["i"])
    absolute_start = payload["i"] * store.chunk_size
    range_start = payload.get("s", 0); range_end = payload.get("e", manifest["size"] - 1)
    left = max(0, range_start - absolute_start)
    right = min(len(body), range_end - absolute_start + 1)
    body = body[left:right]
    next_index = payload["i"] + 1
    last_index = range_end // store.chunk_size
    next_token = store.token(payload["a"], payload["g"], next_index,
                             start=range_start, end=range_end) if next_index <= last_index else None
    return {"body": body, "token": ({"arbitrary_data": next_token} if next_token else None)}


def admin_routes(app, store, token_check, prefix="/_pyre/assets"):
    """Register authenticated list/verify/delete/GC management routes."""
    if not isinstance(store, AssetStore): raise TypeError("store must be AssetStore")
    if callable(token_check): check = token_check
    elif isinstance(token_check, str): check = lambda value: compare_digest(value, token_check)
    else:
        accepted = tuple(token_check)
        check = lambda value: any(compare_digest(value, item) for item in accepted)

    def guarded(handler):
        def inner(request):
            header = request.headers.get("authorization", "")
            token = header[7:].strip() if header[:7].lower() == "bearer " else ""
            if not token or not check(token):
                return Response.json({"error": "unauthorized"}, status=401,
                                     headers=[("www-authenticate", 'Bearer realm="pyre-assets"')])
            return handler(request)
        inner.__name__ = handler.__name__
        return inner

    def list_handler(_request):
        return Response.json({"namespace": store.namespace, "assets": store.list_assets(),
                              "chunk_size": store.chunk_size})

    def manifest_handler(request):
        body = request.json()
        state = store.begin(
            body.get("asset_id"), size=body.get("size"), sha256=body.get("sha256"),
            content_type=body.get("content_type"), session_id=body.get("session_id"),
        )
        # Report already present chunks so interrupted clients resume without
        # retransmitting them. Presence never implies final hash validity.
        present = [index for index in range(state["chunks"])
                   if store._chunk_key(state["generation"], index) in kv.keys()]
        return Response.json({"session": state, "present": present,
                              "chunk_size": store.chunk_size})

    def chunk_handler(request):
        body = request.json()
        try:
            data = base64.b64decode(str(body.get("data", "")).encode("ascii"), validate=True)
        except Exception:
            raise AssetStoreError("chunk data must be canonical base64")
        existed = store.put_chunk(body.get("session_id"), body.get("index"), data)
        return Response.json({"ok": True, "already_present": existed})

    def finalize_handler(request):
        manifest = store.finalize(request.json().get("session_id"))
        return Response.json({"asset": manifest})

    def verify_handler(request):
        body = request.json(); asset_id = body.get("asset_id")
        return Response.json(store.verify(asset_id))

    def delete_handler(request):
        body = request.json()
        return Response.json(store.delete(body.get("asset_id"), limit=int(body.get("limit", 25))))

    def gc_handler(request):
        body = request.json() if request.body else {}
        return Response.json({"results": store.garbage_collect(limit=int(body.get("limit", 25)))})

    # Import locally above would hide the stable backend from Kybra's scanner;
    # pyre.kv itself remains bound by generated main.py.
    app.router.add("POST", prefix + "/manifest", guarded(manifest_handler))
    app.router.add("POST", prefix + "/chunk", guarded(chunk_handler))
    app.router.add("POST", prefix + "/finalize", guarded(finalize_handler))
    app.router.add("GET", prefix + "/list", guarded(list_handler), update=False)
    app.router.add("POST", prefix + "/verify", guarded(verify_handler))
    app.router.add("POST", prefix + "/delete", guarded(delete_handler))
    app.router.add("POST", prefix + "/gc", guarded(gc_handler))
    return prefix
