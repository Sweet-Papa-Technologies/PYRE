"""Shared versioned chunk store for static and generalized assets."""

import base64
import hashlib
import json
import re

from pyre import kv
from pyre._namespace import framework_key, list_prefix

SCHEMA = 1
DEFAULT_CHUNK_SIZE = 45_000
MIN_CHUNK_SIZE = 1_024
MAX_CHUNK_SIZE = 45_000
DEFAULT_MAX_ASSET_BYTES = 500_000_000
MAX_CHUNKS_PER_ASSET = 512
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


class AssetStoreError(ValueError):
    code = "PYRE-ASSET-ERROR"


class AssetNotFound(AssetStoreError):
    code = "PYRE-ASSET-NOT-FOUND"


class AssetQuotaExceeded(AssetStoreError):
    code = "PYRE-ASSET-QUOTA"


class AssetConflict(AssetStoreError):
    code = "PYRE-ASSET-CONFLICT"


def legacy_static_manifest(path):
    """Compatibility reader for the existing `static:<path>:meta` key."""
    return kv.get("static:%s:meta" % path)


def read_legacy_static(path, variant="raw"):
    """Read an existing raw/gzip static generation without migrating it."""
    manifest = legacy_static_manifest(path)
    if manifest is None: raise AssetNotFound("legacy static asset not found")
    if variant not in ("raw", "gzip"): raise AssetStoreError("unknown legacy variant")
    if variant == "gzip" and not manifest.get("gzip"):
        raise AssetNotFound("legacy gzip variant not found")
    count = manifest["chunks"] if variant == "raw" else manifest["gzip_chunks"]
    tag = "c" if variant == "raw" else "gz"
    chunks = []
    for index in range(count):
        encoded = kv.get("static:%s:%s:%d" % (path, tag, index))
        if encoded is None: raise AssetStoreError("legacy static asset is missing chunk %d" % index)
        chunks.append(base64.b64decode(encoded.encode("ascii")))
    return b"".join(chunks)


def validate_name(value, label):
    if not isinstance(value, str) or not _NAME.match(value) or ".." in value:
        raise AssetStoreError("%s must be a safe 1-160 character identifier" % label)
    return value


def validate_content_type(value):
    value = str(value or "application/octet-stream")
    if "\r" in value or "\n" in value or len(value) > 256:
        raise AssetStoreError("invalid content type")
    return value


class ChunkStore:
    def __init__(self, namespace, *, max_asset_bytes=DEFAULT_MAX_ASSET_BYTES,
                 max_namespace_bytes=DEFAULT_MAX_ASSET_BYTES,
                 max_total_bytes=DEFAULT_MAX_ASSET_BYTES, chunk_size=DEFAULT_CHUNK_SIZE):
        self.namespace = validate_name(namespace, "namespace")
        if not MIN_CHUNK_SIZE <= int(chunk_size) <= MAX_CHUNK_SIZE:
            raise ValueError("chunk_size must be between %d and %d" % (MIN_CHUNK_SIZE, MAX_CHUNK_SIZE))
        self.chunk_size = int(chunk_size)
        self.max_asset_bytes = int(max_asset_bytes)
        self.max_namespace_bytes = int(max_namespace_bytes)
        self.max_total_bytes = int(max_total_bytes)
        if min(self.max_asset_bytes, self.max_namespace_bytes, self.max_total_bytes) <= 0:
            raise ValueError("quotas must be positive")

    def _key(self, kind, identity): return framework_key("assets", SCHEMA, kind, self.namespace + ":" + identity)
    def _manifest_key(self, asset_id): return self._key("manifest", validate_name(asset_id, "asset_id"))
    def _session_key(self, session_id): return self._key("session", validate_name(session_id, "session_id"))
    def _chunk_key(self, generation, index, staging=False): return self._key("stage" if staging else "chunk", "%s:%d" % (generation, index))

    def namespace_bytes(self):
        marker = ":manifest:" + self.namespace + "%3A"
        return sum(int(kv.get(key, {}).get("size", 0)) for key in list_prefix("assets", SCHEMA) if marker in key)

    def total_bytes(self):
        return sum(int(kv.get(key, {}).get("size", 0)) for key in list_prefix("assets", SCHEMA) if ":manifest:" in key)

    def begin(self, asset_id, *, size, sha256, content_type=None, session_id=None):
        asset_id = validate_name(asset_id, "asset_id"); size = int(size)
        if size < 0 or size > self.max_asset_bytes: raise AssetQuotaExceeded("asset size exceeds quota")
        old = kv.get(self._manifest_key(asset_id), {})
        old_size = int(old.get("size", 0))
        if self.namespace_bytes() - old_size + size > self.max_namespace_bytes:
            raise AssetQuotaExceeded("namespace total exceeds quota")
        if self.total_bytes() - old_size + size > self.max_total_bytes:
            raise AssetQuotaExceeded("global asset total exceeds quota")
        if not re.match(r"^[0-9a-f]{64}$", str(sha256)): raise AssetStoreError("sha256 must be 64 lowercase hex characters")
        session_id = validate_name(session_id or hashlib.sha256((asset_id + ":" + sha256).encode()).hexdigest()[:32], "session_id")
        generation = hashlib.sha256((self.namespace + ":" + asset_id + ":" + sha256).encode()).hexdigest()
        chunks = max(1, (size + self.chunk_size - 1) // self.chunk_size)
        if chunks > MAX_CHUNKS_PER_ASSET:
            raise AssetQuotaExceeded(
                "asset needs %d chunks; safe finalization limit is %d (increase chunk_size or reduce the asset)"
                % (chunks, MAX_CHUNKS_PER_ASSET)
            )
        desired = {"schema": SCHEMA, "session_id": session_id, "asset_id": asset_id, "size": size, "sha256": sha256, "content_type": validate_content_type(content_type), "generation": generation, "chunks": chunks, "chunk_size": self.chunk_size, "finalized": False}
        existing = kv.get(self._session_key(session_id))
        if existing:
            comparable = dict(existing); comparable["finalized"] = False
            if comparable != desired: raise AssetConflict("session id already describes another upload")
            if not existing["finalized"]:
                return dict(existing)  # resume an in-progress upload
            live = kv.get(self._manifest_key(asset_id))
            if live and live.get("generation") == existing["generation"]:
                return dict(existing)  # already published and still live: idempotent
            # The generation was deleted or superseded, so its finalized session
            # is stale. Fall through to reopen a fresh session; otherwise
            # identical content could never be re-uploaded (put_chunk would
            # reject the finalized session).
        kv.set(self._session_key(session_id), desired)
        return dict(desired)

    def put_chunk(self, session_id, index, data):
        session = kv.get(self._session_key(session_id))
        if not session: raise AssetNotFound("unknown upload session")
        if session["finalized"]: raise AssetConflict("upload session is finalized")
        index = int(index)
        if index < 0 or index >= session["chunks"]: raise AssetStoreError("chunk index out of range")
        data = bytes(data)
        expected = self.chunk_size if index < session["chunks"] - 1 else session["size"] - self.chunk_size * index
        if len(data) != expected: raise AssetStoreError("chunk %d must contain %d bytes" % (index, expected))
        # Chunks are immutable and addressed by the expected content
        # generation. They are not live until finalize atomically publishes
        # the manifest pointer, so a second copy/promotion pass is unnecessary.
        key = self._chunk_key(session["generation"], index)
        encoded = base64.b64encode(data).decode("ascii")
        existing = kv.get(key)
        if existing is not None and existing != encoded: raise AssetConflict("conflicting chunk data")
        kv.set(key, encoded)
        return existing is not None

    def finalize(self, session_id):
        session = kv.get(self._session_key(session_id))
        if not session: raise AssetNotFound("unknown upload session")
        if session["finalized"]: return self.get_manifest(session["asset_id"])
        digest = hashlib.sha256(); total = 0
        for index in range(session["chunks"]):
            encoded = kv.get(self._chunk_key(session["generation"], index))
            if encoded is None: raise AssetStoreError("missing chunk %d" % index)
            data = base64.b64decode(encoded.encode("ascii")); total += len(data); digest.update(data)
        if total != session["size"] or digest.hexdigest() != session["sha256"]: raise AssetConflict("asset size or sha256 verification failed")
        old = kv.get(self._manifest_key(session["asset_id"]))
        manifest = {key: session[key] for key in ("schema", "asset_id", "size", "sha256", "content_type", "generation", "chunks", "chunk_size")}
        kv.set(self._manifest_key(session["asset_id"]), manifest)
        # Generations are content-deterministic and chunks are shared/immutable,
        # so re-publishing a previously-superseded generation makes it live
        # again. Clear any pending GC tombstone for it or GC would delete the
        # now-live chunks.
        kv.delete(self._key("garbage", manifest["generation"]))
        if old and old.get("generation") != manifest["generation"]:
            # Publication stays atomic; the now-unreferenced generation is
            # reclaimed later in bounded GC batches.
            kv.set(self._key("garbage", old["generation"]), {
                "schema": SCHEMA, "generation": old["generation"],
                "chunks": old["chunks"], "next": 0,
            })
        session["finalized"] = True; kv.set(self._session_key(session_id), session)
        return dict(manifest)

    def get_manifest(self, asset_id, generation=None):
        manifest = kv.get(self._manifest_key(asset_id))
        if not manifest or (generation is not None and manifest["generation"] != generation): raise AssetNotFound("asset or generation not found")
        if manifest.get("schema") != SCHEMA: raise AssetStoreError("unsupported asset schema")
        return manifest

    def read_chunk(self, asset_id, generation, index):
        manifest = self.get_manifest(asset_id, generation); index = int(index)
        if index < 0 or index >= manifest["chunks"]: raise AssetNotFound("asset chunk not found")
        encoded = kv.get(self._chunk_key(generation, index))
        if encoded is None: raise AssetNotFound("asset chunk not found")
        return base64.b64decode(encoded.encode("ascii")), manifest

    def read(self, asset_id):
        manifest = self.get_manifest(asset_id)
        return b"".join(self.read_chunk(asset_id, manifest["generation"], i)[0] for i in range(manifest["chunks"]))

    def list_assets(self):
        marker = ":manifest:" + self.namespace + "%3A"
        assets = []
        for key in list_prefix("assets", SCHEMA):
            if marker in key:
                manifest = kv.get(key)
                if manifest:
                    assets.append(dict(manifest))
        return sorted(assets, key=lambda item: item["asset_id"])

    def verify(self, asset_id):
        manifest = self.get_manifest(asset_id)
        digest, total = hashlib.sha256(), 0
        for index in range(manifest["chunks"]):
            body, _ = self.read_chunk(asset_id, manifest["generation"], index)
            total += len(body); digest.update(body)
        return {
            "asset_id": asset_id,
            "ok": total == manifest["size"] and digest.hexdigest() == manifest["sha256"],
            "size": total,
            "sha256": digest.hexdigest(),
        }

    def delete(self, asset_id, limit=25):
        """Bounded, resumable deletion; returns progress information."""
        if not isinstance(limit, int) or limit < 1 or limit > 1_000:
            raise ValueError("delete limit must be between 1 and 1000")
        asset_id = validate_name(asset_id, "asset_id")
        tombstone_key = self._key("delete", asset_id)
        tombstone = kv.get(tombstone_key)
        if tombstone is None:
            manifest = self.get_manifest(asset_id)
            tombstone = {"schema": SCHEMA, "asset_id": asset_id,
                         "generation": manifest["generation"],
                         "chunks": manifest["chunks"], "next": 0}
            # Removing the live pointer first makes subsequent callbacks fail
            # safely while physical chunks are reclaimed over bounded calls.
            kv.delete(self._manifest_key(asset_id))
        removed = 0
        while tombstone["next"] < tombstone["chunks"] and removed < limit:
            kv.delete(self._chunk_key(tombstone["generation"], tombstone["next"]))
            tombstone["next"] += 1; removed += 1
        complete = tombstone["next"] >= tombstone["chunks"]
        if complete: kv.delete(tombstone_key)
        else: kv.set(tombstone_key, tombstone)
        return {"asset_id": asset_id, "removed_chunks": removed,
                "remaining_chunks": tombstone["chunks"] - tombstone["next"],
                "complete": complete}

    def garbage_collect(self, limit=25):
        """Resume bounded deletion and old-generation cleanup."""
        delete_marker = ":delete:" + self.namespace + "%3A"
        results, remaining = [], int(limit)
        if remaining < 1 or remaining > 1_000: raise ValueError("gc limit must be between 1 and 1000")
        for key in list_prefix("assets", SCHEMA):
            if delete_marker not in key or remaining <= 0: continue
            tombstone = kv.get(key)
            result = self.delete(tombstone["asset_id"], limit=remaining)
            results.append(result); remaining -= result["removed_chunks"]
        garbage_marker = ":garbage:" + self.namespace + "%3A"
        for key in list_prefix("assets", SCHEMA):
            if garbage_marker not in key or remaining <= 0: continue
            record = kv.get(key)
            removed = 0
            while record["next"] < record["chunks"] and remaining > 0:
                kv.delete(self._chunk_key(record["generation"], record["next"]))
                record["next"] += 1; removed += 1; remaining -= 1
            complete = record["next"] >= record["chunks"]
            if complete: kv.delete(key)
            else: kv.set(key, record)
            results.append({"generation": record["generation"],
                            "removed_chunks": removed,
                            "remaining_chunks": record["chunks"] - record["next"],
                            "complete": complete})
        return results

    def token(self, asset_id, generation, next_chunk, start=0, end=None, chunk_size=None):
        payload = {"v": 1, "n": self.namespace, "a": asset_id, "g": generation,
                   "i": int(next_chunk), "c": int(chunk_size) if chunk_size is not None else self.chunk_size}
        if start: payload["s"] = int(start)
        if end is not None: payload["e"] = int(end)
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")

    @staticmethod
    def decode_token(token):
        if not isinstance(token, str) or len(token) > 512: raise AssetStoreError("invalid streaming token")
        try: payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode())
        except Exception: raise AssetStoreError("invalid streaming token")
        if not {"v", "n", "a", "g", "i", "c"} <= set(payload) or set(payload) - {"v", "n", "a", "g", "i", "c", "s", "e"} or payload["v"] != 1:
            raise AssetStoreError("invalid streaming token shape")
        validate_name(payload["n"], "namespace"); validate_name(payload["a"], "asset_id")
        if not re.match(r"^[0-9a-f]{64}$", payload["g"]) or not isinstance(payload["i"], int): raise AssetStoreError("invalid streaming token values")
        for name in ("s", "e"):
            if name in payload and (not isinstance(payload[name], int) or payload[name] < 0):
                raise AssetStoreError("invalid streaming token range")
        if not isinstance(payload["c"], int) or not MIN_CHUNK_SIZE <= payload["c"] <= MAX_CHUNK_SIZE:
            raise AssetStoreError("invalid streaming token chunk size")
        if "s" in payload and "e" in payload and payload["s"] > payload["e"]:
            raise AssetStoreError("invalid streaming token range")
        return payload
