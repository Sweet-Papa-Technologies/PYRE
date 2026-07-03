"""PyrePress configuration constants.

Author token: writes are gated by a bearer token. The canister stores only
a sha256 *hash* (pyre.auth guardrail). The default below is for local dev —
CHANGE IT BEFORE DEPLOYING by either editing DEFAULT_TOKEN_SHA256 here, or
rotating at runtime: `PUT /api/meta {"token": "<new-secret>"}` (stores the
new hash under kv "auth:token_sha256", which always wins over the default).
"""

import hashlib

# sha256("pyrepress-dev-token") — dev default only.
DEFAULT_TOKEN = "pyrepress-dev-token"
DEFAULT_TOKEN_SHA256 = hashlib.sha256(DEFAULT_TOKEN.encode("utf-8")).hexdigest()

# kv keys
TOKEN_HASH_KEY = "auth:token_sha256"
META_KEY = "meta:config"
GOOGLE_CLIENT_ID_KEY = "auth:google_client_id"  # Phase C: OIDC audience
# LOCAL-ONLY test hook: when this kv flag is truthy the "dev" login provider
# is enabled (mints a session from a plaintext token, NO signature check).
# OFF by default so a default/mainnet deploy can never mint dev sessions.
# Enable for local e2e via bearer-gated PUT /api/meta {"dev_login": true}.
DEV_LOGIN_KEY = "auth:dev_login"

# Phase C — Google OAuth 2.0 Web client id (PUBLIC, not a secret). It is the
# OIDC `aud` the canister enforces. Set it at runtime with
#   PUT /api/meta {"google_client_id": "…apps.googleusercontent.com"}
# (stored under GOOGLE_CLIENT_ID_KEY, which always wins over this default),
# or bake a default here before deploying.
DEFAULT_GOOGLE_CLIENT_ID = ""

DEFAULT_META = {
    "title": "PyrePress",
    "description": "A certified, tamper-proof blog running inside an "
    "Internet Computer canister — built on PYRE.",
    "author": "FoFo",
    "base_url": "",  # set to the canister URL for absolute RSS links
}

# Certified list page size (the canonical first page at GET /api/posts).
FIRST_PAGE_LIMIT = 10
# RSS feed size.
FEED_LIMIT = 20

# Static-SPA upload token — the deploy-time bearer secret the asset pusher
# (`pyre assets push dist/ --token …`) presents to the authenticated
# /_pyre/static upload routes (pyre.static.admin_routes). Deploy-time secret,
# NOT the author bearer token; rotate before mainnet (edit here, or accept a
# hash-checking callable). Canister state is readable by node providers, so a
# raw literal is only acceptable for a low-value deploy token.
STATIC_UPLOAD_TOKEN = "pyrepress-deploy-token"
