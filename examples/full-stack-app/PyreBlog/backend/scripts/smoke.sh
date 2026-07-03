#!/usr/bin/env bash
# PyrePress smoke test — paste-ready curl walk of the whole API.
#
#   BASE=http://127.0.0.1:8000 ./scripts/smoke.sh                  # pyre dev
#   BASE="http://$(dfx canister id pyrepress).localhost:4943" ./scripts/smoke.sh
#   BASE="https://<canister>.icp0.io" ./scripts/smoke.sh           # mainnet
#
# TOKEN defaults to the dev token; override for a rotated deployment.
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-pyrepress-dev-token}"
AUTH=(-H "Authorization: Bearer ${TOKEN}")
JSON=(-H "Content-Type: application/json")

# Uncertified 2xx GETs (query variant, draft preview) fail response
# verification on the certifying gateway once certified /api paths exist
# (see FRICTION log) — the platform's escape hatch is the raw subdomain.
# pyre dev has no gateway, so RAW_BASE == BASE there.
RAW_BASE="${RAW_BASE:-$(echo "${BASE}" | sed -E 's/\.(localhost|icp0\.io|ic0\.app)/.raw.\1/')}"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

step "health (certified)"
curl -fsS -i "${BASE}/api/health" | sed -n '1p;/^ic-certificate/Ip;/^IC-Certificate/p'
curl -fsS "${BASE}/api/health"; echo

step "meta"
curl -fsS "${BASE}/api/meta"; echo

step "seed demo content (bearer, idempotent)"
curl -fsS -X POST "${AUTH[@]}" "${BASE}/api/seed"; echo

step "certified first page"
curl -fsS "${BASE}/api/posts" | head -c 400; echo

step "filtered + paginated query variant (raw domain: uncertified read)"
curl -fsS "${RAW_BASE}/api/posts/query?tag=icp&limit=2" | head -c 400; echo

step "single post (certified path) — look for IC-Certificate on-chain"
curl -fsS -i "${BASE}/api/posts/pyre-v1-1-announcement" | sed -n '1p;/^ic-certificate/Ip'
curl -fsS "${BASE}/api/posts/pyre-v1-1-announcement" | head -c 300; echo

step "anonymous view counter"
curl -fsS -X POST "${BASE}/api/posts/pyre-v1-1-announcement/view"; echo

step "unauthenticated write is refused"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${JSON[@]}" \
  -d '{"title":"nope","markdown":"x"}' "${BASE}/api/posts")
echo "POST /api/posts without token -> ${code} (expect 401)"

step "create + edit + delete round trip (bearer)"
curl -fsS -X POST "${AUTH[@]}" "${JSON[@]}" \
  -d '{"title":"Smoke Test Post","markdown":"# hi from smoke.sh","status":"published","tags":["smoke"]}' \
  "${BASE}/api/posts" | head -c 300; echo
curl -fsS -X PUT "${AUTH[@]}" "${JSON[@]}" \
  -d '{"markdown":"# edited"}' "${BASE}/api/posts/smoke-test-post" | head -c 200; echo
curl -fsS -X DELETE "${AUTH[@]}" "${BASE}/api/posts/smoke-test-post"; echo

step "RSS 2.0 feed"
curl -fsS -i "${BASE}/api/feed.xml" | sed -n '1p;/^content-type/Ip'
curl -fsS "${BASE}/api/feed.xml" | head -c 300; echo

step "draft is hidden without token, visible with (preview = uncertified -> raw)"
anon=$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/api/posts/roadmap-notes")
auth=$(curl -s -o /dev/null -w '%{http_code}' "${AUTH[@]}" "${RAW_BASE}/api/posts/roadmap-notes")
echo "anon -> ${anon} (expect 404), author -> ${auth} (expect 200)"

printf '\n\033[1mSmoke test complete.\033[0m\n'
