# Generalized assets and streaming

`pyre.assets` extends the existing static store without changing `static:` or
`staticup:` keys. New namespaces use `__pyre:assets:1:` and immutable generation
hashes:

```python
from pyre import assets

media = assets.AssetStore("media", max_total_bytes=500_000_000)
assets.admin_routes(app, media, token_check=ASSET_ADMIN_TOKEN)

@app.get("/media/{asset_id}")
def download(req):
    return media.response(req.path_params["asset_id"], request=req, stream=True)
```

Upload a file with `pyre assets push movie.mp4 --namespace media --url URL
--token TOKEN`. `list`, `verify`, and bounded `delete` use the same URL/token.
Uploads are resumable and idempotent; finalization checks size and SHA-256 before
switching the live manifest. Quotas apply before accepting a manifest.

Large public responses return one 45 KB-or-smaller chunk and an immutable,
generation-bound callback token. This first milestone is public and uncertified;
do not use it for private media. The callback does not replay authentication
middleware. A single byte range is supported; multiple ranges return 416.

Refresh older generated `main.py` files to add
`pyre_http_streaming_callback`. Deletion removes the live pointer immediately
and reclaims chunks in bounded resumable batches. Content types and tokens reject
control characters and malformed shapes.

