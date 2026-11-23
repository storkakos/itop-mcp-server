#!/usr/bin/env bash
# Container smoke test: builds the image with docker compose, waits until healthy and checks the
# running container from outside (HTTP on the published port), like an MCP client would.
# Uses its own compose project, env file, port and log folder; your .env and ./logs are not touched.
# A fake iTop runs next to the server (scripts/smoke.compose.yaml); no real iTop is needed.
#
#   scripts/smoke-test.sh            # exits non-zero on the first failed check
#   SMOKE_PORT=18131 scripts/smoke-test.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT=itop-mcp-smoke
SERVICE=itop-mcp-server
PORT="${SMOKE_PORT:-18130}"
BASE="http://127.0.0.1:${PORT}"
PUBLIC_HOST=mcp.smoke.test
RESOURCE_URL="https://${PUBLIC_HOST}/mcp"
ITOP_URL=http://fake-itop:8080
ISSUER="${ITOP_URL}/env-production/altioo-oauth-server"
TOKEN="smoke-token-$(date +%s)-${RANDOM}${RANDOM}"
WORK="$PWD/.smoke"
LOG_DIR="$WORK/logs"
AUDIT="$LOG_DIR/mcp-itop-audit.log"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/itop_mcp_poc/__init__.py)"
IMAGE="$(sed -n 's/^ *image: *\(itop-mcp-server:[^ ]*\) *$/\1/p' compose.yaml)"

failures=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/        /'; failures=$((failures + 1)); }
check() { local name="$1"; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }
die() { printf 'smoke test aborted: %s\n' "$1" >&2; failures=$((failures + 1)); exit 1; }

compose() {
  MCP_ENV_FILE="$WORK/smoke.env" MCP_LOG_DIR="$LOG_DIR" MCP_PUBLISH_PORT="$PORT" \
  SMOKE_IMAGE="$IMAGE" SMOKE_TOKEN="$TOKEN" \
    docker compose -p "$PROJECT" -f compose.yaml -f scripts/smoke.compose.yaml "$@"
}

# helpers usable with check (bash runs functions through "$@")
startup_logged() { compose logs --no-color "$SERVICE" | grep -q 'iTop MCP-Server auf'; }
audit_has_whoami() { grep -q '"tool": "whoami"' "$AUDIT"; }
token_not_in_audit() { ! grep -Fq "$TOKEN" "$AUDIT"; }
root_fs_not_writable() { compose exec -T "$SERVICE" sh -c '! touch /app/probe 2>/dev/null'; }

cleanup() {
  if [ "$1" -ne 0 ]; then
    echo "--- docker compose logs (last 60 lines) ---"
    compose logs --no-color 2>/dev/null | tail -n 60 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap 'cleanup $?' EXIT

command -v docker >/dev/null || die "docker not found"
command -v curl >/dev/null || die "curl not found"
[ -n "$VERSION" ] || die "no __version__ in src/itop_mcp_poc/__init__.py"
[ -n "$IMAGE" ] || die "no image: line in compose.yaml"

rm -rf "$WORK"
mkdir -p "$LOG_DIR"
chmod 0777 "$LOG_DIR"   # the container runs as UID 10001
cat > "$WORK/smoke.env" <<EOF
ITOP_BASE_URL=$ITOP_URL
MCP_RESOURCE_URL=$RESOURCE_URL
EOF

echo "== build and start ($IMAGE, port $PORT)"
compose build || die "image build failed"
compose up -d --wait --wait-timeout 120 || die "containers did not become healthy"

echo "== image and container"
check "image tag matches project version $VERSION" [ "$IMAGE" = "itop-mcp-server:$VERSION" ]
in_image="$(docker run --rm "$IMAGE" python -c 'import itop_mcp_poc; print(itop_mcp_poc.__version__)')"
check "version inside the image is $VERSION" [ "$in_image" = "$VERSION" ]
cid="$(compose ps -q "$SERVICE")"
check "container is healthy" [ "$(docker inspect -f '{{.State.Health.Status}}' "$cid")" = healthy ]
check "restart policy unless-stopped" [ "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$cid")" = unless-stopped ]
check "root filesystem is read-only" [ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$cid")" = true ]
check "runs as non-root user" [ "$(compose exec -T "$SERVICE" id -u | tr -d '\r')" != 0 ]
check "cannot write outside the log folder" root_fs_not_writable
published="$(compose port "$SERVICE" 8130)"
check "port published on 127.0.0.1 only ($published)" [ "$published" = "127.0.0.1:$PORT" ]

echo "== HTTP"
headers="$(curl -sS -o /dev/null -D - -X POST "$BASE/mcp" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')"
if printf '%s' "$headers" | head -n1 | grep -q ' 401'; then pass "/mcp without token -> 401"; else fail "/mcp without token -> 401" "$headers"; fi
if printf '%s' "$headers" | grep -iq '^www-authenticate: *bearer.*resource_metadata='; then
  pass "WWW-Authenticate with resource_metadata"
else
  fail "WWW-Authenticate with resource_metadata" "$headers"
fi

meta="$(curl -sS "$BASE/.well-known/oauth-protected-resource/mcp")"
if printf '%s' "$meta" | grep -Fq "\"resource\":\"$RESOURCE_URL\""; then pass "metadata resource = $RESOURCE_URL"; else fail "metadata resource" "$meta"; fi
if printf '%s' "$meta" | grep -Fq "\"$ISSUER"; then pass "metadata issuer = $ISSUER"; else fail "metadata issuer" "$meta"; fi

whoami='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"whoami","arguments":{}}}'
body="$(curl -sS -w '\n%{http_code}' -X POST "$BASE/mcp" -H "Host: $PUBLIC_HOST" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' --data "$whoami")"
status="${body##*$'\n'}"
if [ "$status" = 421 ]; then
  fail "Host: $PUBLIC_HOST is accepted (got 421: reverse-proxy host refused)" "$body"
elif [ "$status" = 200 ] && printf '%s' "$body" | grep -q 'Max Muster'; then
  pass "Host: $PUBLIC_HOST with valid token -> 200, whoami answered"
else
  fail "Host: $PUBLIC_HOST with valid token -> 200" "$body"
fi

echo "== logs"
check "application log on stdout (docker logs)" startup_logged
check "audit line for whoami in the host log folder" audit_has_whoami
check "token not in the audit log" token_not_in_audit

echo "== audit log survives down + up"
compose down >/dev/null 2>&1
compose up -d --wait --wait-timeout 120 >/dev/null 2>&1 || die "containers did not come back"
check "audit line still there after recreate" audit_has_whoami

echo "== missing required values"
out="$(docker run --rm "$IMAGE" 2>&1)" && rc=0 || rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q 'ITOP_BASE_URL'; then pass "no ITOP_BASE_URL -> exit $rc, named"; else fail "no ITOP_BASE_URL -> named error" "$out"; fi
out="$(docker run --rm -e ITOP_BASE_URL=https://itop.example.test "$IMAGE" 2>&1)" && rc=0 || rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q 'MCP_RESOURCE_URL'; then pass "no MCP_RESOURCE_URL -> exit $rc, named"; else fail "no MCP_RESOURCE_URL -> named error" "$out"; fi

echo
if [ "$failures" -ne 0 ]; then
  echo "smoke test FAILED: $failures check(s)"
  exit 1
fi
echo "smoke test passed"
