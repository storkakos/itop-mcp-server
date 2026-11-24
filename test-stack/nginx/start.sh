#!/bin/sh
# TEST ONLY. Entrypoint of the nginx proxy (compose.nginx.yaml). Builds the server block of
# mcp.example.com from the two nginx code blocks of the README section "Reverse proxy (TLS)", so the
# README is what the check list tests. The stack fills in only what the README leaves to the reader:
# the upstreams (127.0.0.1:8130 -> mcp / mcp-prefix) and the certificate paths. A missing or
# changed block stops the proxy here, a block that nginx refuses stops it at "nginx -t"; either way
# the check list fails.
set -eu

README=/stack/README.md
OUT=/etc/nginx/conf.d/mcp-from-readme.conf

fail() { echo "nginx-from-readme: $*" >&2; exit 1; }

# The n-th ```nginx block of the section "## Reverse proxy (TLS)".
block() {
  awk -v n="$1" '
    /^## / { sec = ($0 == "## Reverse proxy (TLS)") }
    sec && /^```nginx[[:space:]]*$/ { if (++c == n) { on = 1; next } }
    on && /^```[[:space:]]*$/ { exit }
    on { print }' "$README"
}

server=$(block 1)
prefix=$(block 2)
[ -n "$server" ] || fail "README: first nginx block (proxy in front of the MCP server) not found"
[ -n "$prefix" ] || fail "README: second nginx block (path prefix) not found"
for b in "$server" "$prefix"; do
  printf '%s\n' "$b" | grep -q '127\.0\.0\.1:8130' || fail "README: an nginx block has no upstream 127.0.0.1:8130"
done
printf '%s\n' "$server" | grep -q '/etc/ssl/mcp\.example\.com/fullchain\.pem' || fail "README: certificate path not found"
printf '%s\n' "$server" | grep -q '/etc/ssl/mcp\.example\.com/privkey\.pem' || fail "README: key path not found"
[ "$(printf '%s\n' "$server" | tail -n 1)" = "}" ] || fail "README: first nginx block does not end with the server's }"

{
  echo "# Generated at start-up from README.md by test-stack/nginx/start.sh. Do not edit."
  # The server block without its closing }, then the path-prefix locations inside it, then the }.
  printf '%s\n' "$server" | sed '$d' \
    | sed -e 's#127\.0\.0\.1:8130#mcp:8130#g' \
          -e 's#/etc/ssl/mcp\.example\.com/fullchain\.pem#/certs/site.crt#' \
          -e 's#/etc/ssl/mcp\.example\.com/privkey\.pem#/certs/site.key#'
  echo
  echo "    # --- README, path prefix (MCP server with MCP_RESOURCE_URL=https://mcp.example.com/itop-mcp/mcp)"
  printf '%s\n' "$prefix" | sed -e 's#127\.0\.0\.1:8130#mcp-prefix:8130#g' -e 's#^#    #'
  echo "}"
} > "$OUT"

echo "nginx-from-readme: wrote $OUT"
cat "$OUT"
nginx -t
exec nginx -g 'daemon off;'
