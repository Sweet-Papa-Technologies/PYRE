#!/usr/bin/env bash
# e2e_integrated.sh — prove the INTEGRATED PyrePress canister end-to-end on a
# local replica: one canister serving BOTH the Vue SPA (at /) and the /api
# backend, all through the NORMAL (non-raw) gateway subdomain.
#
# Prereqs:
#   * local replica running (dfx start) with the backend deployed
#     (backend/dfx.json canister `pyrepress`)
#   * the SPA built + pushed:  see README "Build, deploy, upload"
#
# Usage:
#   CID=<canister-id> ./scripts/e2e_integrated.sh
#   BASE=http://<id>.localhost:4943 ./scripts/e2e_integrated.sh
#
# Env:
#   CID    canister id (default: read from backend/.dfx/local/canister_ids.json)
#   PORT   replica port (default 4943)
#   TOKEN  author bearer token (default pyrepress-dev-token)
#   SLUG   a published post slug to read (default pyre-v1-1-announcement)
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-4943}"
if [ -z "${CID:-}" ]; then
  CID="$(python3 -c 'import json;print(json.load(open("backend/.dfx/local/canister_ids.json"))["pyrepress"]["local"])' 2>/dev/null)"
fi
BASE="${BASE:-http://${CID}.localhost:${PORT}}"
TOKEN="${TOKEN:-pyrepress-dev-token}"
SLUG="${SLUG:-pyre-v1-1-announcement}"
AUTH=(-H "Authorization: Bearer ${TOKEN}")
JSON=(-H "Content-Type: application/json")

pass=0; fail=0
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
check() { # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then printf '  \033[32mPASS\033[0m %s (%s)\n' "$1" "$2"; pass=$((pass+1))
  else printf '  \033[31mFAIL\033[0m %s (got %s, want %s)\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
hdr()  { curl -s -D - -o /dev/null "$@"; }

echo "BASE=${BASE}  (normal, non-raw gateway)"

step "SPA served from the canister (GET /, certified index)"
check "GET / status"            "$(code "${BASE}/")" 200
check "GET / has IC-Certificate" "$(hdr "${BASE}/" | grep -ci '^ic-certificate:')" 1
check "GET / is html"           "$(curl -s "${BASE}/" | grep -qi '<html\|<!doctype html' && echo 1 || echo 0)" 1

step "SPA client-side route falls back to index (deep link)"
check "GET /post/${SLUG} status" "$(code -H 'Accept: text/html' "${BASE}/post/${SLUG}")" 200
check "deep link is html"        "$(curl -s -H 'Accept: text/html' "${BASE}/post/${SLUG}" | grep -qi '<html' && echo 1 || echo 0)" 1

step "hashed JS asset served with JS content-type"
ASSET="$(curl -s "${BASE}/" | grep -oE '/assets/[^"]+\.js' | head -1)"
echo "  asset: ${ASSET}"
check "asset status"       "$(code "${BASE}${ASSET}")" 200
check "asset content-type" "$(hdr "${BASE}${ASSET}" | grep -ci 'content-type: *text/javascript')" 1

step "certified reads (GET /api/posts, GET /api/posts/{slug})"
check "GET /api/posts status" "$(code "${BASE}/api/posts")" 200
check "GET /api/posts/${SLUG} status" "$(code "${BASE}/api/posts/${SLUG}")" 200
check "post has IC-Certificate" "$(hdr "${BASE}/api/posts/${SLUG}" | grep -ci '^ic-certificate:')" 1
check "post is certified JSON with slug+html" \
  "$(curl -s "${BASE}/api/posts/${SLUG}" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['post']['slug']=='${SLUG}' and bool(d['post']['html']) and d['verify']['certified'] is True)")" True

step "view counter increments (POST /api/posts/{slug}/view)"
V1="$(curl -s -X POST "${BASE}/api/posts/${SLUG}/view" | python3 -c 'import sys,json;print(json.load(sys.stdin)["views"])')"
V2="$(curl -s -X POST "${BASE}/api/posts/${SLUG}/view" | python3 -c 'import sys,json;print(json.load(sys.stdin)["views"])')"
check "view count increments" "$((V2 - V1))" 1

step "RSS feed (GET /api/feed.xml)"
check "feed status" "$(code "${BASE}/api/feed.xml")" 200
check "feed is RSS"  "$(curl -s "${BASE}/api/feed.xml" | grep -ci '<rss')" 1

step "author loop (bearer): admin list incl. drafts, F16 update route"
check "GET /api/admin/posts no-token" "$(code "${BASE}/api/admin/posts")" 401
check "GET /api/admin/posts bearer"   "$(code "${AUTH[@]}" "${BASE}/api/admin/posts")" 200
# create a draft, then publish it via the SPA's publish verb
curl -s -X POST "${AUTH[@]}" "${JSON[@]}" \
  -d '{"title":"E2E Draft","slug":"e2e-draft","markdown":"# hi from e2e","status":"draft"}' \
  "${BASE}/api/posts" >/dev/null
check "draft hidden from public" "$(code "${BASE}/api/posts/e2e-draft")" 404
check "publish status" "$(code -X POST "${AUTH[@]}" "${BASE}/api/posts/e2e-draft/publish")" 200
check "published post now public" "$(code "${BASE}/api/posts/e2e-draft")" 200
curl -s -X DELETE "${AUTH[@]}" "${BASE}/api/posts/e2e-draft" >/dev/null  # cleanup

step "comments loop (OIDC MOCKED via gated 'dev' provider)"
check "unauth comment submit -> 401" \
  "$(code -X POST "${JSON[@]}" -d '{"body":"anon"}' "${BASE}/api/posts/${SLUG}/comments")" 401
# enable the local-only dev login provider (bearer-gated)
curl -s -X PUT "${AUTH[@]}" "${JSON[@]}" -d '{"dev_login":true}' "${BASE}/api/meta" >/dev/null
SID="$(curl -s -X POST "${JSON[@]}" -d '{"provider":"dev","token":"e2e-reader|reader@e2e.local|E2E Reader"}' \
  "${BASE}/api/auth/login" | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_id"])')"
check "dev login minted a session" "$(printf '%s' "$SID" | wc -c | tr -d ' ')" 64
CID_COMMENT="$(curl -s -X POST "${JSON[@]}" -H "X-Session-Id: ${SID}" \
  -d '{"body":"e2e authenticated comment"}' "${BASE}/api/posts/${SLUG}/comments" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')"
echo "  pending comment id: ${CID_COMMENT}"
check "pending hidden from certified list" \
  "$(curl -s "${BASE}/api/posts/${SLUG}/comments" | python3 -c "import sys,json;print(any(c['id']=='${CID_COMMENT}' for c in json.load(sys.stdin)['items']))")" False
check "moderation queue bearer-gated (F16 update route)" \
  "$(code "${AUTH[@]}" "${BASE}/api/comments/pending")" 200
curl -s -X POST "${AUTH[@]}" "${BASE}/api/comments/${CID_COMMENT}/approve" >/dev/null
check "approved comment appears in certified list" \
  "$(curl -s "${BASE}/api/posts/${SLUG}/comments" | python3 -c "import sys,json;print(any(c['id']=='${CID_COMMENT}' for c in json.load(sys.stdin)['items']))")" True
check "approved-comments list has IC-Certificate" \
  "$(hdr "${BASE}/api/posts/${SLUG}/comments" | grep -ci '^ic-certificate:')" 1
# disable the dev provider again
curl -s -X PUT "${AUTH[@]}" "${JSON[@]}" -d '{"dev_login":false}' "${BASE}/api/meta" >/dev/null

printf '\n\033[1m== summary ==\033[0m  \033[32m%d passed\033[0m, \033[31m%d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
