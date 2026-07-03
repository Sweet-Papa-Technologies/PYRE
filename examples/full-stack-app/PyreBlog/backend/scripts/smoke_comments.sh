#!/usr/bin/env bash
# PyrePress Phase C smoke test — sessions, comments, moderation.
#
#   BASE="http://$(dfx canister id pyrepress).localhost:4943" ./scripts/smoke_comments.sh
#   BASE="https://<canister>.icp0.io" ./scripts/smoke_comments.sh   # mainnet
#
# TOKEN  = author bearer token (moderation).  Default: dev token.
# ID_TOKEN = a real Google ID token from Google Identity Services (browser),
#            OR a token your registered test provider accepts. If unset, the
#            login step is SKIPPED and the script only exercises the
#            unauthenticated-refusal + certified-empty-list paths.
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-pyrepress-dev-token}"
ID_TOKEN="${ID_TOKEN:-}"
PROVIDER="${PROVIDER:-google}"
SLUG="${SLUG:-hello-pyrepress}"
AUTH=(-H "Authorization: Bearer ${TOKEN}")
JSON=(-H "Content-Type: application/json")
RAW_BASE="${RAW_BASE:-$(echo "${BASE}" | sed -E 's/\.(localhost|icp0\.io|ic0\.app)/.raw.\1/')}"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

step "seed content + ensure the post exists"
curl -fsS -X POST "${AUTH[@]}" "${BASE}/api/seed" >/dev/null && echo "seeded"

step "unauthenticated comment submit is refused (expect 401)"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${JSON[@]}" \
  -d '{"body":"anon"}' "${BASE}/api/posts/${SLUG}/comments")
echo "POST comment without session -> ${code}"

step "certified approved-comments list (empty until something is approved)"
curl -fsS -i "${BASE}/api/posts/${SLUG}/comments" | sed -n '1p;/^ic-certificate/Ip'
curl -fsS "${BASE}/api/posts/${SLUG}/comments"; echo

step "moderation queue requires the author token (expect 401 then 200)"
# The moderation list is an UNCERTIFIED 2xx GET, so a certifying gateway 503s
# it once certified paths exist — read author-only screens via the raw domain.
anon=$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/api/comments/pending")
curl -fsS "${AUTH[@]}" "${RAW_BASE}/api/comments/pending" >/dev/null && echo "anon -> ${anon}, author (raw) -> 200"

if [ -z "${ID_TOKEN}" ]; then
  printf '\n\033[33mID_TOKEN unset — skipping the authenticated login/submit/approve loop.\033[0m\n'
  printf 'Set ID_TOKEN=<google id token> (and register google_client_id via PUT /api/meta) to run it.\n'
  exit 0
fi

step "reader login -> session"
SID=$(curl -fsS -X POST "${JSON[@]}" \
  -d "{\"provider\":\"${PROVIDER}\",\"token\":\"${ID_TOKEN}\"}" \
  "${BASE}/api/auth/login" | sed -E 's/.*"session_id":"([^"]+)".*/\1/')
echo "session_id: ${SID:0:12}…"

step "session check (query-fast)"
curl -fsS -H "X-Session-Id: ${SID}" "${BASE}/api/auth/me"; echo

step "authenticated submit -> pending"
CID=$(curl -fsS -X POST "${JSON[@]}" -H "X-Session-Id: ${SID}" \
  -d '{"body":"Verified reader says hi from smoke_comments.sh"}' \
  "${BASE}/api/posts/${SLUG}/comments" | sed -E 's/.*"id":"([^"]+)".*/\1/')
echo "pending comment id: ${CID}"

step "oversized body is rejected (expect 413)"
BIG=$(head -c 2100 </dev/zero | tr '\0' 'x')
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${JSON[@]}" -H "X-Session-Id: ${SID}" \
  -d "{\"body\":\"${BIG}\"}" "${BASE}/api/posts/${SLUG}/comments")
echo "oversized -> ${code}"

step "still hidden before approval"
curl -fsS "${BASE}/api/posts/${SLUG}/comments"; echo

step "author approves -> appears in certified list"
curl -fsS -X POST "${AUTH[@]}" "${BASE}/api/comments/${CID}/approve" >/dev/null
curl -fsS -i "${BASE}/api/posts/${SLUG}/comments" | sed -n '1p;/^ic-certificate/Ip'
curl -fsS "${BASE}/api/posts/${SLUG}/comments"; echo

step "logout invalidates the session (expect 401 on /me)"
curl -fsS -X POST -H "X-Session-Id: ${SID}" "${BASE}/api/auth/logout" >/dev/null
code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-Session-Id: ${SID}" "${BASE}/api/auth/me")
echo "me after logout -> ${code}"

printf '\n\033[1mPhase C smoke test complete.\033[0m\n'
