# Test stack for the setup manuals

**Test only, not for production.** Every password, key and secret in this folder is a test value.
Nothing here is needed to run the MCP server; production uses the `compose.yaml` in the repo root.

This stack reproduces the validation run of the two manuals on one Docker host:

- [iTop prerequisites](../docs/setup/itop-prerequisites.md)
- [Example setup: Keycloak and LibreChat](../docs/setup/example-keycloak-librechat.md)

It starts a TLS proxy (Caddy) for `itop.example.com`, `sso.example.com`, `chat.example.com` and
`mcp.example.com`, MariaDB, iTop 3.2.3, Mailpit, Keycloak 26.8.2, MongoDB, LibreChat v0.8.9 and the
MCP server built from this repo. Inside the stack's network the four hostnames point to the proxy,
so no hosts file is needed for the checks.

## What you need

- Docker with Compose v2.24 or later, about 6 GB of free disk space, internet access
- `openssl` and `sh` for the certificates
- For check 7 (a chat answer): your own LLM API key, see [LLM key](#llm-key)

## Run it

```sh
cd test-stack
./make-certs.sh                                   # test CA + certificate, in certs/ (git-ignored)
docker compose up -d --build                      # first start: downloads iTop and installs it
docker compose logs -f setup                      # wait for "setup complete" (about 5 minutes)
docker compose run --rm client python checks.py   # runs both check lists
```

`checks.py` prints one line per check (`PASS`, `FAIL` or `SKIP`) and exits with 1 if a check failed.
`python checks.py -v` adds the traceback of a failed check.

Start over from a clean state: `docker compose down -v` (removes the volumes, including the
downloads), then the commands above again.

## What the stack does, and where it follows the manuals

| Step | Done by | Manual |
|---|---|---|
| Download iTop 3.2.3-3, altioo-oauth-server 0.1.0, combodo-hybridauth 2.1.1; check SHA256; stop on a mismatch | `itop/entrypoint.sh` | prerequisites, "Extensions" |
| Install a plain iTop 3.2.3 (the "existing iTop", without extensions) | `itop/entrypoint.sh`, `itop/install.xml` | (prerequisite of the manual) |
| Apache vhost: reverse-proxy settings and the `.well-known` rewrite | `itop/itop.conf` | prerequisites, "Web server rewrites", "PHP behind a reverse proxy" |
| Copy the extensions, make the config writable, run the setup wizard as an upgrade | `client/setup.py`, `client/wizard.py` (drives the wizard pages like a browser) | prerequisites, steps 2-4 |
| Edit `config-itop.php` | `client/config_edits.py` | prerequisites, "Configure iTop"; example, "iTop: log in with Keycloak" |
| Realm `example`, clients `itop` and `librechat`, email lock-down, test users | `client/keycloak_realm.py` (admin REST API, the manual's values) | example, Keycloak sections |
| LibreChat `.env` and `librechat.yaml` | `librechat/` | example, "LibreChat" |
| Check lists | `client/checks.py` | both "Check list" sections |

Differences from the manuals, all for a local test: the Keycloak realm is created (the manual
assumes it exists) with Mailpit as SMTP; the client secrets are fixed test values instead of being
copied from the Credentials tab; the iTop admin gets the REST Services User profile so the setup can
create test users through REST; the config edits are checked by iTop still answering instead of
`php -l`.

Test users:

| User | Where | Password | iTop profile |
|---|---|---|---|
| `admin` | iTop (local) | `Test-Admin-Pw1!` | Administrator |
| `lena.local` | iTop (local) | `Test-Lena-Pw1!` | Service Desk Agent |
| `anna` / `anna@example.com` | Keycloak, iTop External user | `Test-Anna-Pw1!` | Service Desk Agent |
| `bob` / `bob@example.com` | Keycloak, iTop External user | `Test-Bob-Pw1!` | Support Agent |
| `admin` | Keycloak `master` realm | `test-kc-admin-pw` | |

## LLM key

LibreChat needs a model with tool calls for check 7. The example uses OpenRouter. Put your key into
`test-stack/llm.env`, which is git-ignored and never committed:

```sh
umask 077
echo 'OPENROUTER_KEY=<your key>' > llm.env
docker compose up -d librechat        # pick up the key
```

For another provider, change the endpoint in `librechat/librechat.yaml` and the key name in
`llm.env`. Without `llm.env`, `checks.py` skips check 7 and says so.

## Reach the services with IP and port (optional)

The checks need no published ports. To reach every service from another machine, add
`compose.ports.yaml`:

```sh
docker compose -f compose.yaml -f compose.ports.yaml up -d
```

| Service | Host port (variable) | What |
|---|---|---|
| proxy | 443 (`TEST_HTTPS_PORT`) | HTTPS for all four hostnames |
| iTop | 8081 (`TEST_ITOP_PORT`) | iTop's Apache, plain HTTP |
| Keycloak | 8080 (`TEST_KEYCLOAK_PORT`), 9000 (`TEST_KEYCLOAK_MGMT_PORT`) | admin console; management |
| LibreChat | 3080 (`TEST_LIBRECHAT_PORT`) | plain HTTP |
| MCP server | 8130 (`TEST_MCP_PORT`) | plain HTTP, e.g. `/.well-known/oauth-protected-resource/mcp` |
| Mailpit | 8025 (`TEST_MAIL_UI_PORT`), 1025 (`TEST_MAIL_SMTP_PORT`) | web UI with the verification mails; SMTP |
| MariaDB | 3306 (`TEST_DB_PORT`) | user `itop`, password `test-itop-db-pw` |
| MongoDB | 27017 (`TEST_MONGO_PORT`) | no authentication |

If another stack on the host already uses a port, set the variable, e.g.
`TEST_HTTPS_PORT=8443 TEST_ITOP_PORT=18081 docker compose -f compose.yaml -f compose.ports.yaml up -d`.

What works with IP and port: Keycloak's admin console, Mailpit, the databases, the MCP server's
metadata, and looking at iTop and LibreChat. **Logins and the OAuth flows need the hostnames**: iTop,
Keycloak and LibreChat send the browser to `https://*.example.com` (port 443). For those, map the
four hostnames to the Docker host in your hosts file, publish the proxy on port 443, and trust
`certs/ca.crt` in your browser (or accept the certificate warning once per hostname).

## In a browser on another machine, without admin rights

Changing the hosts file needs admin rights. On Windows, `browser/open-browser.ps1` does without:
it starts a browser with its own profile that resolves the four hostnames to the Docker host, and
it can trust the test CA for your Windows user only.

1. Publish the proxy on port 443 (see above):
   `docker compose -f compose.yaml -f compose.ports.yaml up -d`
2. Copy `certs/ca.crt` from the Docker host to your machine.
3. In PowerShell (no admin rights), in `test-stack/browser/`:

   ```powershell
   .\open-browser.ps1 -HostIp <Docker host IP> -CaFile <path to ca.crt> -Shortcut
   ```

   Windows asks once whether to trust the test CA: answer **Yes**. The browser opens
   `https://chat.example.com` and `https://itop.example.com`; `-Shortcut` puts a desktop shortcut
   to open it again.

| `-Browser` | How it resolves the hostnames | Note |
|---|---|---|
| `firefox` (default) | profile setting `network.dns.forceResolve`: **every** hostname goes to the Docker host | use that profile only for the test stack |
| `edge`, `chrome` | `--host-resolver-rules` for the four hostnames only | |

The profiles live in `%USERPROFILE%\.itop-mcp-test\`, apart from your normal browser profile. To
undo: delete that folder and the desktop shortcut, and remove the test CA in `certmgr.msc`
(Trusted Root Certification Authorities, "itop-mcp test CA"). If the PowerShell execution policy
blocks the script, start it with `powershell -ExecutionPolicy Bypass -File .\open-browser.ps1 ...`.

## Notes

- LibreChat limits logins per IP (about 7 in 5 minutes). Running `checks.py` several times in a row
  can end with `auth_rate_limited`; wait five minutes.
- The stack uses the names `itop-mcp-test-*` for its project, images and volumes.
