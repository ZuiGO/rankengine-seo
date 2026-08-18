#!/bin/bash
# verify_rest_api.sh — Phase 1A REST API smoke test
# Verifies that WP Application Password auth works and that PATCH succeeds.
# Run from sandbox/wp-docker/ after `docker compose up -d` and provisioning completes.
#
# Usage: ./verify_rest_api.sh
# Prerequisites: docker compose up -d, wpcli container must have finished

set -e

SANDBOX_URL="http://localhost:8091"
NGINX_USER="sandbox"
NGINX_PASS="sandbox123"
WP_USER="admin"

PASS_FAIL=0

echo "=================================================="
echo "  RankEngine WP Sandbox — REST API Verification"
echo "=================================================="
echo ""

# ------------------------------------------------------------------ #
# Step 1: Extract application password from wpcli logs
# ------------------------------------------------------------------ #
echo "Step 1: Reading Application Password from wpcli logs..."
APP_PASS=$(docker compose logs wpcli 2>/dev/null | grep "Password:" | grep -v "Admin" | awk '{print $NF}' | tail -1)
if [ -z "$APP_PASS" ]; then
  echo "  ERROR: Could not extract Application Password from logs."
  echo "  Run: docker compose logs wpcli | grep 'Password:'"
  echo "  Then set: export APP_PASS='xxxx xxxx xxxx xxxx xxxx xxxx'"
  PASS_FAIL=1
else
  echo "  Found: ${APP_PASS}"
fi

if [ -z "$APP_PASS" ] && [ -n "$RANKENGINE_WP_APP_PASS" ]; then
  APP_PASS="$RANKENGINE_WP_APP_PASS"
  echo "  Using env var RANKENGINE_WP_APP_PASS"
fi

if [ -z "$APP_PASS" ]; then
  echo "  FAIL: No application password available. Aborting."
  exit 1
fi

# ------------------------------------------------------------------ #
# Step 2: Unauthenticated GET — find the Railways page ID
# ------------------------------------------------------------------ #
echo ""
echo "Step 2: GET /wp-json/wp/v2/pages?slug=railways (unauthenticated)..."
RESPONSE=$(curl -s -u "${NGINX_USER}:${NGINX_PASS}" \
  "${SANDBOX_URL}/wp-json/wp/v2/pages?slug=railways")
PAGE_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; pages=json.load(sys.stdin); print(pages[0]['id'] if pages else '')" 2>/dev/null)

if [ -z "$PAGE_ID" ]; then
  echo "  FAIL: Could not find Railways page. Response: ${RESPONSE:0:200}"
  PASS_FAIL=1
else
  echo "  OK: Railways page ID = ${PAGE_ID}"
fi

# ------------------------------------------------------------------ #
# Step 3: GET with Basic Auth — verify Yoast meta is present
# ------------------------------------------------------------------ #
echo ""
echo "Step 3: Verify Yoast meta via REST (yoast_head field)..."
YOAST_CHECK=$(curl -s -u "${NGINX_USER}:${NGINX_PASS}" \
  "${SANDBOX_URL}/wp-json/wp/v2/pages/${PAGE_ID}?_fields=id,slug,yoast_head" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('PRESENT' if d.get('yoast_head') else 'MISSING')" 2>/dev/null)
echo "  yoast_head: ${YOAST_CHECK}"

# ------------------------------------------------------------------ #
# Step 4: PATCH title via Application Password — THE KEY TEST
# ------------------------------------------------------------------ #
ORIGINAL_TITLE="Railways"
TEST_TITLE="REST API Patch Test — RankEngine"

echo ""
echo "Step 4: PATCH /wp-json/wp/v2/pages/${PAGE_ID} with Application Password..."
PATCH_RESPONSE=$(curl -s -w "\n%{http_code}" \
  -u "${NGINX_USER}:${NGINX_PASS}" \
  -H "Authorization: Basic $(echo -n "${WP_USER}:${APP_PASS}" | base64)" \
  -H "Content-Type: application/json" \
  -X POST \
  "${SANDBOX_URL}/wp-json/wp/v2/pages/${PAGE_ID}" \
  -d "{\"title\": \"${TEST_TITLE}\"}")
HTTP_CODE=$(echo "$PATCH_RESPONSE" | tail -1)
RESPONSE_BODY=$(echo "$PATCH_RESPONSE" | head -1)

if [ "$HTTP_CODE" = "200" ]; then
  UPDATED_TITLE=$(echo "$RESPONSE_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title',{}).get('rendered',''))" 2>/dev/null)
  if [ "$UPDATED_TITLE" = "$TEST_TITLE" ]; then
    echo "  PASS: HTTP 200, title updated to: '${UPDATED_TITLE}'"
  else
    echo "  WARN: HTTP 200 but title was '${UPDATED_TITLE}' (expected '${TEST_TITLE}')"
  fi
else
  echo "  FAIL: HTTP ${HTTP_CODE}"
  echo "  Response: ${RESPONSE_BODY:0:500}"
  PASS_FAIL=1
fi

# ------------------------------------------------------------------ #
# Step 5: Revert title to original
# ------------------------------------------------------------------ #
echo ""
echo "Step 5: Reverting title to '${ORIGINAL_TITLE}'..."
REVERT_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -u "${NGINX_USER}:${NGINX_PASS}" \
  -H "Authorization: Basic $(echo -n "${WP_USER}:${APP_PASS}" | base64)" \
  -H "Content-Type: application/json" \
  -X POST \
  "${SANDBOX_URL}/wp-json/wp/v2/pages/${PAGE_ID}" \
  -d "{\"title\": \"${ORIGINAL_TITLE}\"}")
echo "  Revert HTTP: ${REVERT_CODE}"

# ------------------------------------------------------------------ #
# Step 6: Check robots.txt
# ------------------------------------------------------------------ #
echo ""
echo "Step 6: GET /robots.txt..."
ROBOTS=$(curl -s -u "${NGINX_USER}:${NGINX_PASS}" "${SANDBOX_URL}/robots.txt")
if echo "$ROBOTS" | grep -q "Disallow: /"; then
  echo "  PASS: robots.txt contains 'Disallow: /'"
else
  echo "  WARN: robots.txt content: '${ROBOTS:0:100}'"
fi

# ------------------------------------------------------------------ #
# Step 7: Check noindex meta
# ------------------------------------------------------------------ #
echo ""
echo "Step 7: Check noindex meta tag on Railways page..."
PAGE_HTML=$(curl -s -u "${NGINX_USER}:${NGINX_PASS}" "${SANDBOX_URL}/railways/")
if echo "$PAGE_HTML" | grep -qi "noindex"; then
  echo "  PASS: noindex directive present"
else
  echo "  WARN: noindex not found in page HTML (check WP Settings > Reading)"
fi

# ------------------------------------------------------------------ #
# Summary
# ------------------------------------------------------------------ #
echo ""
echo "=================================================="
if [ "$PASS_FAIL" -eq 0 ]; then
  echo "  ALL CHECKS PASSED ✅"
  echo "  Application Password REST auth: CONFIRMED"
  echo "  Phase 4 WordPress connector: READY TO BUILD"
else
  echo "  SOME CHECKS FAILED ❌"
  echo "  Review output above before proceeding to Phase 4."
fi
echo "=================================================="
echo ""
echo "  Credentials for Phase 4 connector:"
echo "  WP_SANDBOX_URL=${SANDBOX_URL}"
echo "  WP_SANDBOX_NGINX_USER=${NGINX_USER}"
echo "  WP_SANDBOX_NGINX_PASS=${NGINX_PASS}"
echo "  WP_SANDBOX_WP_USER=${WP_USER}"
echo "  WP_SANDBOX_APP_PASS=${APP_PASS}"
echo "  WP_SANDBOX_PAGE_ID=${PAGE_ID}"
