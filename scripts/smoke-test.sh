#!/usr/bin/env bash
# Container smoke test: builds the image with docker compose, waits until healthy and checks the
# running container from outside (HTTP on the published port), like an MCP client would.
# Uses its own compose project, env file, port and log folder; your .env and ./logs are not touched.
# A fake iTop runs next to the server (scripts/smoke.compose.yaml); no real iTop is needed. It speaks
# HTTPS with a certificate from a throwaway test CA, which is mounted into the server read-only and
# named in SSL_CERT_FILE, exactly like a customer with an internal CA does it.
#
#   scripts/smoke-test.sh            # exits non-zero on the first failed check
#   SMOKE_PORT=18131 SMOKE_PROJECT=smoke-b scripts/smoke-test.sh   # second run next to the first
set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT="${SMOKE_PROJECT:-itop-mcp-smoke}"
SERVICE=itop-mcp-server
PORT="${SMOKE_PORT:-18130}"
BASE="http://127.0.0.1:${PORT}"
PUBLIC_HOST=mcp.smoke.test
RESOURCE_URL="https://${PUBLIC_HOST}/mcp"
ITOP_URL=https://fake-itop:8080
CA_IN_CONTAINER=/etc/itop-mcp/ca.pem   # same target as the commented example in compose.yaml
ISSUER="${ITOP_URL}/env-production/altioo-oauth-server"
TOKEN="smoke-token-$(date +%s)-${RANDOM}${RANDOM}"
WORK="$PWD/.smoke"
LOG_DIR="$WORK/logs"
AUDIT="$LOG_DIR/mcp-itop-audit.log"
CA_DIR="$WORK/ca"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/itop_mcp_server/__init__.py)"
IMAGE="$(sed -n 's/^ *image: *\(itop-mcp-server:[^ ]*\) *$/\1/p' compose.yaml)"
# Own tag per compose project, so parallel smoke runs on one Docker host don't replace each other's image.
RUN_IMAGE="$IMAGE-$PROJECT"

failures=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/        /'; failures=$((failures + 1)); }
check() { local name="$1"; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }
die() { printf 'smoke test aborted: %s\n' "$1" >&2; failures=$((failures + 1)); exit 1; }

compose() {
  MCP_ENV_FILE="$WORK/smoke.env" MCP_LOG_DIR="$LOG_DIR" MCP_PUBLISH_PORT="$PORT" \
  SMOKE_IMAGE="$RUN_IMAGE" SMOKE_TOKEN="$TOKEN" SMOKE_CA_DIR="$CA_DIR" SMOKE_CA_TARGET="$CA_IN_CONTAINER" \
    docker compose -p "$PROJECT" -f compose.yaml -f scripts/smoke.compose.yaml "$@"
}

# helpers usable with check (bash runs functions through "$@")
# Read the logs first: piped straight into grep -q, docker compose logs can die of SIGPIPE after the
# match, and pipefail then fails the check although the line is there.
startup_logged() { local logs; logs="$(compose logs --no-color "$SERVICE")" && grep -q 'iTop MCP-Server auf' <<<"$logs"; }
audit_has_whoami() { grep -q '"tool": "whoami"' "$AUDIT"; }
token_not_in_audit() { ! grep -Fq "$TOKEN" "$AUDIT"; }
root_fs_not_writable() { compose exec -T "$SERVICE" sh -c '! touch /app/probe 2>/dev/null'; }
# HTTPS from inside the server container to the fake iTop, with the container's own environment
# or with SSL_CERT_FILE cleared (= the image's built-in public CAs only).
https_to_itop() { compose exec -T "$@" "$SERVICE" python -c "import httpx; httpx.get('$ITOP_URL/')" >/dev/null 2>&1; }
itop_trusted_with_ca() { https_to_itop; }
# Without SSL_CERT_FILE the request must fail on certificate verification itself. Any other outcome
# (connected, name not resolved, fake iTop down) prints what happened and exits non-zero, so a
# refused connection cannot pass for "verification stays on".
itop_cert_refusal() {
  compose exec -T -e SSL_CERT_FILE= "$SERVICE" python - "$ITOP_URL/" 2>&1 <<'PY'
import ssl, sys
import httpx
try:
    httpx.get(sys.argv[1])
except Exception as exc:
    cause = exc
    while cause is not None and not isinstance(cause, ssl.SSLCertVerificationError):
        cause = cause.__cause__ or cause.__context__
    if cause is None:
        sys.exit(f"not a certificate error: {exc!r}")
    print(f"SSLCertVerificationError: {cause.verify_message}")
else:
    sys.exit("connected: the certificate was accepted")
PY
}
image_has_no_ssl_cert_file() { [ -z "$(docker run --rm "$RUN_IMAGE" printenv SSL_CERT_FILE)" ]; }

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
[ -n "$VERSION" ] || die "no __version__ in src/itop_mcp_server/__init__.py"
[ -n "$IMAGE" ] || die "no image: line in compose.yaml"

rm -rf "$WORK"
mkdir -p "$LOG_DIR" "$CA_DIR"
chmod 0777 "$LOG_DIR"   # the container runs as UID 10001
cat > "$WORK/smoke.env" <<EOF
ITOP_BASE_URL=$ITOP_URL
MCP_RESOURCE_URL=$RESOURCE_URL
SSL_CERT_FILE=$CA_IN_CONTAINER
EOF

echo "== build and start ($RUN_IMAGE, project $PROJECT, port $PORT)"
compose build || die "image build failed"
# Throwaway test CA + certificate for the fake iTop, generated with the image's own Python.
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/tests:/tests:ro" -v "$CA_DIR:/out" "$RUN_IMAGE" \
  python /tests/throwaway_ca.py /out fake-itop || die "test CA generation failed"
chmod 0644 "$CA_DIR"/*.pem   # readable by UID 10001 in both containers (throwaway key, test only)
compose up -d --wait --wait-timeout 120 || die "containers did not become healthy"

echo "== image and container"
check "image tag matches project version $VERSION" [ "$IMAGE" = "itop-mcp-server:$VERSION" ]
in_image="$(docker run --rm "$RUN_IMAGE" python -c 'import itop_mcp_server; print(itop_mcp_server.__version__)')"
check "version inside the image is $VERSION" [ "$in_image" = "$VERSION" ]
cid="$(compose ps -q "$SERVICE")"
check "container is healthy" [ "$(docker inspect -f '{{.State.Health.Status}}' "$cid")" = healthy ]
# Proxy on loopback port 9, where nothing listens: a request sent through it would fail.
check "healthcheck passes with an unreachable HTTP(S)_PROXY and no NO_PROXY" compose exec -T \
  -e HTTP_PROXY=http://127.0.0.1:9 -e HTTPS_PROXY=http://127.0.0.1:9 -e http_proxy=http://127.0.0.1:9 \
  -e https_proxy=http://127.0.0.1:9 -e NO_PROXY= -e no_proxy= "$SERVICE" python -m itop_mcp_server.healthcheck
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
if [ "$status" = 401 ]; then
  fail "Host: $PUBLIC_HOST with valid token -> 200 (got 401: token check against iTop failed, TLS?)" "$body"
elif [ "$status" = 421 ]; then
  fail "Host: $PUBLIC_HOST is accepted (got 421: reverse-proxy host refused)" "$body"
elif [ "$status" = 200 ] && printf '%s' "$body" | grep -q 'Max Muster'; then
  pass "Host: $PUBLIC_HOST with valid token -> 200, whoami answered"
else
  fail "Host: $PUBLIC_HOST with valid token -> 200" "$body"
fi

echo "== internal CA (fake iTop on HTTPS, CA mounted read-only, SSL_CERT_FILE=$CA_IN_CONTAINER)"
check "no SSL_CERT_FILE baked into the image" image_has_no_ssl_cert_file
check "iTop certificate trusted with the mounted CA" itop_trusted_with_ca
name="iTop certificate refused without SSL_CERT_FILE (verification stays on)"
out="$(itop_cert_refusal)" && rc=0 || rc=$?
if [ "$rc" -eq 0 ]; then pass "$name: $out"; else fail "$name" "$out"; fi

echo "== logs"
check "application log on stdout (docker logs)" startup_logged
check "audit line for whoami in the host log folder" audit_has_whoami
check "token not in the audit log" token_not_in_audit

echo "== audit log survives down + up"
compose down >/dev/null 2>&1
compose up -d --wait --wait-timeout 120 >/dev/null 2>&1 || die "containers did not come back"
check "audit line still there after recreate" audit_has_whoami

echo "== missing required values"
out="$(docker run --rm "$RUN_IMAGE" 2>&1)" && rc=0 || rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q 'ITOP_BASE_URL'; then pass "no ITOP_BASE_URL -> exit $rc, named"; else fail "no ITOP_BASE_URL -> named error" "$out"; fi
out="$(docker run --rm -e ITOP_BASE_URL=https://itop.example.test "$RUN_IMAGE" 2>&1)" && rc=0 || rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q 'MCP_RESOURCE_URL'; then pass "no MCP_RESOURCE_URL -> exit $rc, named"; else fail "no MCP_RESOURCE_URL -> named error" "$out"; fi

echo
if [ "$failures" -ne 0 ]; then
  echo "smoke test FAILED: $failures check(s)"
  exit 1
fi
echo "smoke test passed"
