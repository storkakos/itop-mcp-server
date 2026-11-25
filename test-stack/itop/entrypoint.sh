#!/bin/sh
# TEST ONLY. Downloads iTop 3.2.3 and the extensions (pinned to the SHA256 values of
# docs/setup/itop-prerequisites.md), installs a plain iTop once, runs iTop's cron, starts Apache.
set -eu

# The test CA: iTop calls Keycloak over HTTPS from the server.
cp /certs/ca.crt /usr/local/share/ca-certificates/itop-mcp-test-ca.crt
update-ca-certificates >/dev/null 2>&1

fetch() { # file url sha256
  if [ ! -f "/downloads/$1" ]; then
    echo "downloading $1"
    curl -fsSL -o "/downloads/$1.part" "$2"
    mv "/downloads/$1.part" "/downloads/$1"
  fi
  if ! echo "$3  /downloads/$1" | sha256sum -c - >/dev/null 2>&1; then
    echo "SHA256 MISMATCH for $1 (expected $3), stopping. Delete the downloads volume to retry." >&2
    rm -f "/downloads/$1"
    exit 1
  fi
  echo "SHA256 ok: $1"
}

fetch iTop-3.2.3-3.zip "https://sourceforge.net/projects/itop/files/itop/3.2.3-3/iTop-3.2.3-3-21709.zip/download" \
  b233df9d821315ef8f369017f91dc1a26312bcb6fc13cf8f797a2ba1c32b65c2
fetch altioo-oauth-server-0.1.0.zip "https://github.com/AltiooBV/altioo-oauth-server/releases/download/v0.1.0/altioo-oauth-server-0.1.0.zip" \
  d8933b65e2250d029238923efc0a4acff4b80a099b815a43dad97a0d30b6e320
fetch combodo-hybridauth-2.1.1.zip "https://github.com/Combodo/combodo-hybridauth/archive/refs/tags/2.1.1.zip" \
  5ddb33cc94669d65e540d51a484a56fc7b5a38bfe8f73f8709d217653d6ab3e6
# mcp-token-info: built from the repo's itop-extension/mcp-token-info/ (ticket dolibarr-parity 06)
if [ ! -f "/downloads/mcp-token-info-0.1.0.zip" ]; then
  echo "building mcp-token-info-0.1.0.zip"
  (cd /opt/itop-test/mcp-token-info && zip -r /downloads/mcp-token-info-0.1.0.zip . -x "*.git*")
fi

W=/var/www/itop
if [ ! -f "$W/index.php" ]; then
  echo "unpacking iTop"
  rm -rf /tmp/itop && mkdir /tmp/itop
  unzip -q /downloads/iTop-3.2.3-3.zip -d /tmp/itop
  cp -a /tmp/itop/web/. "$W/"
  rm -rf /tmp/itop
  chown -R www-data:www-data "$W"
fi

if [ ! -f "$W/conf/production/config-itop.php" ]; then
  echo "installing a plain iTop 3.2.3 (unattended, without extensions)"
  until mariadb -h db -uitop -ptest-itop-db-pw -e "select 1" itop >/dev/null 2>&1; do sleep 2; done
  cp /opt/itop-test/install.xml /tmp/install.xml && chown www-data /tmp/install.xml
  su -s /bin/sh www-data -c "cd $W/setup/unattended-install && php unattended-install.php \
      --param-file=/tmp/install.xml --installation_xml=$W/datamodels/2.x/installation.xml --clean=1" \
    | tail -3
  rm -f /tmp/install.xml
fi

# iTop cron every minute (requirement in the prerequisites manual). Test credentials.
printf 'auth_user=admin\nauth_pwd=Test-Admin-Pw1!\n' > /run/itop-cron.params
chown www-data /run/itop-cron.params && chmod 600 /run/itop-cron.params
(
  while true; do
    sleep 60
    su -s /bin/sh www-data -c "php $W/webservices/cron.php --param_file=/run/itop-cron.params" >/tmp/cron.log 2>&1 || true
  done
) &

exec docker-php-entrypoint "$@"
