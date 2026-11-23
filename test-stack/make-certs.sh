#!/bin/sh
# TEST ONLY. Creates certs/ca.crt (test CA) and certs/site.crt (itop/sso/chat/mcp.example.com).
# Keeps existing files; delete certs/ to start over. certs/ is git-ignored.
set -eu
cd "$(dirname "$0")"
mkdir -p certs
cd certs
if [ -f ca.crt ] && [ -f site.crt ]; then
  echo "certs/ already exists, keeping it"
  exit 0
fi
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=itop-mcp test CA" \
  -keyout ca.key -out ca.crt \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=example.com" -keyout site.key -out site.csr 2>/dev/null
cat > ext.cnf <<EOF
subjectAltName=DNS:itop.example.com,DNS:sso.example.com,DNS:chat.example.com,DNS:mcp.example.com
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
authorityKeyIdentifier=keyid
EOF
openssl x509 -req -in site.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 -extfile ext.cnf \
  -out site.crt 2>/dev/null
rm -f site.csr ext.cnf ca.srl
# Readable by the containers' users (Caddy, the MCP server runs as UID 10001).
chmod 644 ca.crt site.crt site.key
echo "created certs/ca.crt and certs/site.crt"
