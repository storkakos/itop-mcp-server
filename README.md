# iTop MCP server

An MCP server for iTop, built and run as a Docker container on your own machine. MCP clients such
as LibreChat use it to let users read tickets and CIs from iTop through an AI assistant.

- **Read-only.** The tools only read from iTop. There are no tools that create or change data.
- **Every call runs with the caller's own iTop token.** iTop (with the altioo-oauth-server
  extension) is the authorization server: it logs the user in and issues the token. The MCP server
  forwards that token to iTop's REST/JSON API, so each user sees exactly what iTop allows them to
  see. The server stores no user secrets, issues no tokens and keeps no state between requests.
- **Plain HTTP on `127.0.0.1`.** Your existing reverse proxy terminates TLS in front of it.
- **Audit log** as JSON lines in a host folder. Tokens never appear in any log.

Based on [cdmx-in/itop-mcp](https://github.com/cdmx-in/itop-mcp) (MIT).

New here? The [**quick start for administrators**](docs/quick-start.md) walks through the whole
setup in order, with screenshots, and links to the detailed sections below. For the people who
use the assistant, there is a [**user guide**](docs/user-guide.md).

## Contents

1. [Prerequisites on the iTop side](#prerequisites-on-the-itop-side)
2. [Requirements on the Docker host](#requirements-on-the-docker-host)
3. [Install](#install)
4. [Configuration](#configuration)
5. [Reverse proxy (TLS)](#reverse-proxy-tls)
6. [Internal CA](#internal-ca)
7. [Update and rollback](#update-and-rollback)
8. [Audit log](#audit-log)
9. [Tools and the per-user token model](#tools-and-the-per-user-token-model)
10. [Troubleshooting](#troubleshooting)
11. [Licences](#licences)
12. [Development](#development)

## Prerequisites on the iTop side

Prepare iTop before you start the container:

- [**iTop prerequisites**](docs/setup/itop-prerequisites.md) (required for every customer): the
  altioo-oauth-server extension, `allow_rest_services_via_tokens`, the profiles that may use the
  assistant, the resource entry, web server rewrites and a check list.
- [**Example setup: Keycloak and LibreChat**](docs/setup/example-keycloak-librechat.md) (optional):
  one way to log into iTop through an identity provider and to connect an MCP client.
- [**Test stack**](test-stack/README.md) (test only, not for production): both manuals on one Docker
  host, set up automatically, with a command that runs their check lists.

One thing to get exactly right: in `config-itop.php`, the altioo-oauth-server resource
`resources` → `itop-mcp` → `url` must be **identical, character by character,** to
`MCP_RESOURCE_URL` of this server (same scheme, host, port and path, no extra trailing slash). A
mismatch does not show up as a server error. The OAuth flow starts, the user logs in, and iTop then
says "Unknown resource".

## Requirements on the Docker host

- Docker with the Compose plugin (`docker compose`)
- `git`
- Internet access to Docker Hub and PyPI while building (the image is built on your machine)
- A reverse proxy that terminates TLS (see [Reverse proxy](#reverse-proxy-tls))
- The container must reach iTop over HTTPS

## Install

```sh
# 1. Get a released version
git clone <repository URL> itop-mcp-server
cd itop-mcp-server
git checkout v0.1.0

# 2. Configure: set ITOP_BASE_URL and MCP_RESOURCE_URL
cp .env.example .env
${EDITOR:-vi} .env

# 3. Prepare the log folder BEFORE the first start
mkdir -p logs && sudo chown 10001:10001 logs

# 4. Build and start
docker compose up -d --build

# 5. Check health
docker compose ps        # STATUS shows "(healthy)" after a few seconds
curl -si http://127.0.0.1:8130/mcp -X POST | head -n 1                   # HTTP/1.1 401 Unauthorized
curl -s http://127.0.0.1:8130/.well-known/oauth-protected-resource/mcp   # your resource URL and issuer
```

Step 3 matters: the container runs as UID 10001 and writes the audit log to `./logs`. If the folder
is missing, Docker creates it as root, and the container stops right after starting and restarts in
a loop (see [Troubleshooting](#troubleshooting)). If you set `MCP_LOG_DIR` to another folder,
prepare that one instead.

The metadata path in step 5 is `/.well-known/oauth-protected-resource` followed by the path of
`MCP_RESOURCE_URL` (here `/mcp`). Then put the reverse proxy in front and run the
[check list](docs/setup/itop-prerequisites.md#check-list) against the public URL.

## Configuration

All settings live in `.env` next to `compose.yaml`. [`.env.example`](.env.example) lists each one
with a comment. The container refuses to start when a required value is missing or invalid, and
`docker logs` names the variable.

**Server settings** (passed into the container):

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ITOP_BASE_URL` | yes | | Base URL of your iTop, without a trailing slash, e.g. `https://itop.example.com` |
| `MCP_RESOURCE_URL` | yes | | Public URL of this server as MCP clients reach it through the reverse proxy, e.g. `https://mcp.example.com/mcp`. Must equal the `itop-mcp` resource in iTop. |
| `ITOP_OAUTH_ISSUER` | no | `<ITOP_BASE_URL>/env-production/altioo-oauth-server` | Issuer of the authorization server. Set it only for a non-standard altioo path or a different public iTop host name. |
| `ITOP_API_VERSION` | no | `1.3` | iTop REST API version |
| `MCP_MAX_ROWS` | no | `50` | Maximum number of rows a single tool call fetches from iTop |
| `SSL_CERT_FILE` | no | | CA bundle inside the container for an internal CA, see [Internal CA](#internal-ca) |

**Docker compose settings** (read by `docker compose` itself, only from `.env` or the shell):

| Variable | Default | Meaning |
|---|---|---|
| `MCP_PUBLISH_PORT` | `8130` | Host port, published on `127.0.0.1` only. Point your reverse proxy at it. |
| `MCP_LOG_DIR` | `./logs` | Host folder for the audit log. Must be writable by UID 10001. |

**Inside the container** (normally leave alone):

| Variable | Default | Meaning |
|---|---|---|
| `MCP_AUDIT_LOG` | `/data/logs/mcp-itop-audit.log` | Audit log path inside the container. Keep it in `/data/logs`: anywhere else is read-only and the server refuses to start, except `/tmp`, which is writable but lost when the container is recreated. |
| `MCP_HOST`, `MCP_PORT` | `0.0.0.0`, `8130` | Fixed by `compose.yaml`; setting them in `.env` has no effect. |

After changing `.env`, apply it with `docker compose up -d`.

## Reverse proxy (TLS)

The container speaks plain HTTP on `127.0.0.1:8130` (or `MCP_PUBLISH_PORT`). Your reverse proxy
terminates TLS on the public host name from `MCP_RESOURCE_URL` and forwards to that port. It must:

- forward both `/mcp` and `/.well-known/oauth-protected-resource/mcp` (MCP clients fetch the
  metadata there); forwarding the whole host is simplest
- pass the public `Host` header through. The server only accepts its public host name (from
  `MCP_RESOURCE_URL`) and loopback. A request with any other host gets `421 Misdirected Request`.
  Likewise, an `Origin` header (sent by browser-based clients) must be the origin of
  `MCP_RESOURCE_URL` or loopback, otherwise the request gets `403 Forbidden`. This check comes
  first, on every path including the `.well-known` metadata, and before the bearer token is looked
  at: a refused request gets `421` or `403` with or without a token (never a `401` challenge), and
  nothing is sent to iTop for it.
  Letter case does not matter, and the default port (`443` for `https`, `80` for `http`) may be
  present or left out, both in the `Host` header and in `MCP_RESOURCE_URL` (which must still match
  the `itop-mcp` resource in iTop character for character). A non-default port, as
  in `https://mcp.example.com:8443/mcp`, must be in the `Host` header (`mcp.example.com:8443`).
- pass the `Authorization` header through unchanged

nginx:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name mcp.example.com;

    ssl_certificate     /etc/ssl/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/ssl/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8130;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;   # each iTop request may take up to 60 s; raise this if iTop is slow
    }
}
```

Apache (`mod_proxy`, `mod_proxy_http`, `mod_ssl`):

```apache
<VirtualHost *:443>
    ServerName mcp.example.com
    SSLEngine on
    SSLCertificateFile    /etc/ssl/mcp.example.com/fullchain.pem
    SSLCertificateKeyFile /etc/ssl/mcp.example.com/privkey.pem

    ProxyPreserveHost On
    ProxyTimeout 120
    ProxyPass        / http://127.0.0.1:8130/
    ProxyPassReverse / http://127.0.0.1:8130/
</VirtualHost>
```

If the proxy runs on another machine, it cannot reach `127.0.0.1` on the Docker host. In that case
publish the port on an internal interface in a `compose.override.yaml` and restrict access to the
proxy with your firewall; never expose the plain HTTP port to the network at large.

## Internal CA

If iTop's HTTPS certificate is issued by your own certificate authority, mount the CA bundle (PEM)
read-only and point `SSL_CERT_FILE` at it. Certificate verification is never turned off.

1. Put the bundle on the host, e.g. `certs/internal-ca.pem`, readable by UID 10001
   (`chmod 644 certs/internal-ca.pem`).
2. Create `compose.override.yaml` next to `compose.yaml` (so `compose.yaml` stays unchanged for
   `git pull`; compose reads the override automatically):

   ```yaml
   services:
     itop-mcp-server:
       volumes:
         - ./certs/internal-ca.pem:/etc/itop-mcp/ca.pem:ro
   ```

3. In `.env`: `SSL_CERT_FILE=/etc/itop-mcp/ca.pem`
4. `docker compose up -d`

The bundle **replaces** the built-in list of public CAs. It must contain the CA that issued iTop's
certificate (the root, plus intermediates if iTop does not send them). With a wrong bundle, every
request gets `401` and `docker logs` shows a failed token check
(`Token-Pruefung fehlgeschlagen … iTop nicht erreichbar`). If the file named in `SSL_CERT_FILE`
is missing or unreadable in the container, the log shows
`Token-Pruefung fehlgeschlagen … No such file or directory` (or `Permission denied`) instead.

## Update and rollback

Releases are git tags `vX.Y.Z`. The image is tagged with the same version (`itop-mcp-server:X.Y.Z`),
so `docker image ls itop-mcp-server` shows which versions are built on the host.

Update to a new release:

```sh
git fetch --tags
git checkout v0.2.0          # the new tag
docker compose up -d --build
docker compose ps            # wait for "(healthy)"
```

If you follow a branch instead of tags, `git pull` followed by `docker compose up -d --build` does
the same.

Roll back to the previous release:

```sh
git checkout v0.1.0          # the previous tag
docker compose up -d --build
```

The server keeps no state, so nothing needs migrating either way. `.env`, `compose.override.yaml`,
`logs/` and `certs/` are not tracked by git and stay as they are. Read the release notes of the new
version for new or changed settings in `.env.example`.

## Audit log

Every tool call appends exactly one line to `logs/mcp-itop-audit.log` on the host (`MCP_LOG_DIR`):
also calls the server refuses before they reach iTop, calls where iTop is unreachable or answers
with an error, and calls that are cancelled while they run (for example when the server shuts
down). The file survives container recreation and updates.

```json
{"ts": "2026-11-23T09:14:02", "user": "Jane Doe", "token": "3f9a1c0e7b2d", "tool": "search_tickets", "args": {"text": "printer", "status": "", "class": "UserRequest"}, "ok": true, "info": ""}
```

| Field | Meaning |
|---|---|
| `ts` | Time of the call in the container's time zone (UTC unless you set `TZ`) |
| `user` | iTop person the token belongs to; `?` for refused input (which never reaches iTop), for a cancelled call, or when iTop does not name a person for the token (also when the lookup fails because iTop is unreachable) |
| `token` | Short, non-reversible hash of the token, to tell sessions apart. Never the token itself. |
| `tool` | Tool name |
| `args` | Tool arguments; long token-like strings are masked as `***` |
| `ok` | `true` only if the call reached iTop and **every** iTop request of the call was answered without error, see below |
| `info` | Empty when `ok` is `true`. Otherwise why not: `abgelehnt: …` (refused input), iTop's error message or the connection error (`iTop HTTP 500`, `iTop nicht erreichbar: …`, `iTop lieferte kein JSON …`), `kein iTop-Aufruf: …` (the tool answered without asking iTop) or `abgebrochen` (cancelled). Shortened and masked like `args`. |

How `ok` is decided, for every tool alike:

- **Refused input** (for example an `oql_query` that is not a single `SELECT`): `ok` is `false`.
- **No iTop request at all** (for example a `smart_query_v2` comparison the tool cannot run): `ok`
  is `false`, and `info` starts with `kein iTop-Aufruf:` followed by the first line of the answer.
- **One of several iTop requests failed** (for example one half of a `smart_query_v2`
  comparison): `ok` is `false` and `info` names the first error, even if the tool still answered.
  The server cannot tell whether a tool recovered from the error or only wrote it into its text.
- **`whoami`**: the person lookup is the tool's only iTop request, so a failed lookup gives `ok`
  `false` (and `user` `?`).
- **Cancelled:** `ok` is `false`, `info` is `abgebrochen`. The iTop request may already have run.
- The lookup of `user` for the audit line is a separate iTop request and does not count.

**Rotation is your job.** The server only appends and never rotates or deletes the file. Use
logrotate with `copytruncate` (the server keeps no file handle open between calls, but
`copytruncate` is the safe choice), and keep the files as long as your audit rules require.

The application log (startup, rejected tokens, errors) goes to stdout:
`docker compose logs itop-mcp-server`. It contains no tokens either, only the same short hash.

## Tools and the per-user token model

The MCP client fetches a token for the user from iTop (OAuth with iTop's login and consent page) and
sends it as `Authorization: Bearer …` with every request. The server checks the token with iTop on
every request (no cache), then calls iTop's REST/JSON API with it in the `Auth-Token` header. A
request without a valid token gets `401` with a `WWW-Authenticate` header that points the client to
the [protected-resource metadata](https://www.rfc-editor.org/rfc/rfc9728) and from there to iTop.
An expired or revoked token is refused as soon as iTop refuses it.

All tools are read-only. Results are capped at `MCP_MAX_ROWS` rows.

| Tool | What it does |
|---|---|
| `whoami` | Names the iTop person the assistant is acting as |
| `search_tickets` | Searches tickets by text (title and reference), status and class (`UserRequest`, `Incident`, `Change`, `Problem`, `Ticket`) |
| `get_ticket` | Reads one ticket by reference (e.g. `R-000123`) with description; for user requests and incidents also status, priority and public log |
| `oql_query` | Runs a single OQL `SELECT`; anything else is refused before it reaches iTop |
| `smart_query_v2` | From upstream: turns a natural-language question into an iTop query |
| `list_operations` | From upstream: lists the operations of iTop's REST API |

## Troubleshooting

**The container restarts in a loop, `docker compose ps` never shows "healthy".** Look at
`docker compose logs itop-mcp-server`. The line `iTop MCP-Server auf …` is logged *before* the start-up
checks and does **not** mean a successful start; look at the lines after it.

| Message | Cause and fix |
|---|---|
| `Konfigurationsfehler: Audit-Log … ist nicht beschreibbar (MCP_AUDIT_LOG …)` | With the default configuration: the host folder `./logs` (`MCP_LOG_DIR`) is not owned by UID 10001, usually because Docker created it as root. Fix: `sudo chown 10001:10001 logs`, then `docker compose up -d`, and check the log again. If you set `MCP_AUDIT_LOG`, it must point into `/data/logs`. |
| `Konfigurationsfehler: ITOP_BASE_URL ist nicht gesetzt` (or `MCP_RESOURCE_URL`) | The required value is missing in `.env`, or `.env` is not next to `compose.yaml`. |
| `Konfigurationsfehler: MCP_RESOURCE_URL muss eine http(s)-URL mit Host sein` | Use the full public URL, e.g. `https://mcp.example.com/mcp`. |

**Every request gets `401`, even with a token.** `docker logs` shows why the token check failed:
`Token abgelehnt` means iTop refused the token (expired, revoked, or the user's profile may not use
tokens); `Token-Pruefung fehlgeschlagen … iTop nicht erreichbar` means the container cannot reach
iTop (network, proxy, or certificate, see [Internal CA](#internal-ca)).

**`421 Misdirected Request` through the reverse proxy** (on every path, with or without a token). The
proxy does not pass the public `Host` header, or `MCP_RESOURCE_URL` names another host. See [Reverse proxy](#reverse-proxy-tls).

**The OAuth flow ends with "Unknown resource" in iTop.** `MCP_RESOURCE_URL` and the `itop-mcp`
resource in `config-itop.php` differ. See [Prerequisites on the iTop side](#prerequisites-on-the-itop-side).

More checks with expected output: [check list](docs/setup/itop-prerequisites.md#check-list).

## Licences

- This repository is licensed under the **MIT licence**, see [`LICENSE`](LICENSE).
- This server is a fork of [cdmx-in/itop-mcp](https://github.com/cdmx-in/itop-mcp), which is under
  the MIT licence too. The upstream licence is kept in
  [`LICENSE-upstream-itop-mcp`](LICENSE-upstream-itop-mcp). Both licence files are installed into
  the image.
- **altioo-oauth-server** is licensed under the **GNU AGPL-3.0-or-later**. It is not part of this
  repository: it runs inside your iTop, and you obtain it from Altioo BV. Read its terms before you
  install or offer it. The other iTop extensions and their licences are listed in
  [iTop prerequisites → Licences](docs/setup/itop-prerequisites.md#licences).

## Development

The tests run without Docker and without a real iTop: they start the server against a small fake
iTop and talk to it over HTTP like an MCP client. They need Python 3.13 on Linux (`requirements.lock`
is resolved for Linux); on Windows, run them in a Linux container or VM.

```sh
python -m venv .venv
.venv/bin/pip install --no-deps -r requirements.lock -r requirements-build.lock
.venv/bin/pip install --no-deps --no-build-isolation -e .
.venv/bin/pip install pytest==8.4.2
.venv/bin/pytest
```

The container smoke test needs a Docker host. It builds the image, starts it next to a fake iTop
and checks it from outside, without touching your `.env` or `./logs`:

```sh
scripts/smoke-test.sh
```

Releasing: set `__version__` in `src/itop_mcp_server/__init__.py` and the image tag in `compose.yaml`
to the same version (a test checks this), run both test suites, then tag `vX.Y.Z`.
