# Test stack for the setup manuals

**Test only, not for production.** Every password, key and secret in this folder is a test value.
Nothing here is needed to run the MCP server; production uses the `compose.yaml` in the repo root.

This stack reproduces the validation run of the two manuals on one Docker host:

- [iTop prerequisites](../docs/setup/itop-prerequisites.md)
- [Example setup: Keycloak and LibreChat](../docs/setup/example-keycloak-librechat.md)

It starts a TLS proxy (Caddy, or nginx: see [nginx as TLS proxy](#nginx-as-tls-proxy)) for
`itop.example.com`, `sso.example.com`, `chat.example.com` and `mcp.example.com`, MariaDB, iTop
3.2.3, Mailpit, Keycloak 26.8.2, MongoDB, LibreChat v0.8.9 and the MCP server built from this repo.
Inside the stack's network the four hostnames point to the proxy, so no hosts file is needed for
the checks.

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
docker compose run --rm client python checks.py   # runs both check lists (all groups, see Check groups)
```

`checks.py` prints one line per check (`PASS`, `FAIL` or `SKIP`) and exits with 1 if a check failed.
`python checks.py -v` adds the traceback of a failed check.

Start over from a clean state: `docker compose down -v` (removes the volumes, including the
downloads), then the commands above again.

## Check groups

The checks are split into groups, one file per group in `client/groups/`. The file name is the
group name. Groups run in a fixed order, whatever order you name them in:

| Group | File | Checks | Needs |
|---|---|---|---|
| `prerequisites` | `client/groups/prerequisites.py` | check list of the iTop prerequisites | setup only |
| `proxy` | `client/groups/proxy.py` | the README's reverse proxy blocks (path prefix: nginx variant only, otherwise SKIP) | setup only |
| `example` | `client/groups/example.py` | example setup, Keycloak and iTop: checks 1 to 4, the Keycloak setup run again | setup only |
| `librechat` | `client/groups/librechat.py` | example setup, LibreChat: checks 5 to 8, the preselected iTop assistant | `librechat` (and Mongo) |

"Setup only" means the one-shot `setup` service and what it depends on: proxy, MariaDB, iTop,
Keycloak, Mailpit and the MCP server. LibreChat and Mongo are not needed and need not run.

```sh
docker compose run --rm client python checks.py                          # all groups
docker compose run --rm client python checks.py prerequisites example    # only these (also: prerequisites,example)
docker compose run --rm client python checks.py --list                   # groups and their checks
```

Only groups without LibreChat, on a stack that starts neither LibreChat nor Mongo (clearly less
RAM): start the `setup` service alone (compose starts its dependencies) and wait until it is done:

```sh
docker compose up -d --build setup && docker compose wait setup           # exit code 0: setup complete
docker compose run --rm client python checks.py prerequisites proxy example
```

`python checks.py --services <groups>` prints the services to start for those groups (`setup`, plus
`librechat` for the group `librechat`); `scripts/stack-on-vm.sh --groups` uses it. Before the first
check of the group `librechat`, the checks wait until LibreChat answers (`/health`, and `/api/config`
offers the Keycloak login), up to `LIBRECHAT_READY_TIMEOUT` seconds (default 300). If it does not,
every check of the group fails with "not run: LibreChat at … not ready within … s".

### Add a check

Add it to the group's file, under the other checks of that group:

```python
@check("example 9: what the manual promises, in a few words")
def _():
    ...                       # assert what must hold; an exception makes the check FAIL
    return "detail"           # optional: shown after PASS; return "SKIP <reason>" to skip
```

Checks run in the order of the file. A check may use what an earlier check of the same group left
behind (e.g. the LibreChat sessions in `librechat.py`), never what another group did: each group
must also run alone.

### Add a group

A new file `client/groups/<name>.py` (lowercase letters, digits, `_`), no other file changes:

```python
from checklib import Group

group = Group(__name__, "Heading printed before the checks (the manual it checks)", order=50,
              services=(),     # compose services needed besides the setup, e.g. ("librechat",)
              ready=None)      # optional: called before the first check, to wait for those services
check = group.check
```

`order` places the group among the others (10, 20, 30, 40 are taken). Mention the group in the
table above.

## What the stack does, and where it follows the manuals

| Step | Done by | Manual |
|---|---|---|
| Download iTop 3.2.3-3, altioo-oauth-server 0.1.0, combodo-hybridauth 2.1.1; check SHA256; stop on a mismatch | `itop/entrypoint.sh` | prerequisites, "Extensions" |
| Install a plain iTop 3.2.3 (the "existing iTop", without extensions) | `itop/entrypoint.sh`, `itop/install.xml` | (prerequisite of the manual) |
| Apache vhost: reverse-proxy settings and the `.well-known` rewrite | `itop/itop.conf` | prerequisites, "Web server rewrites", "PHP behind a reverse proxy" |
| Copy the extensions, make the config writable, run the setup wizard as an upgrade | `client/setup.py`, `client/wizard.py` (drives the wizard pages like a browser) | prerequisites, steps 2-4 |
| Edit `config-itop.php` | `client/config_edits.py` | prerequisites, "Configure iTop"; example, "iTop: log in with Keycloak" |
| Realm `example`, clients `itop` (with front-channel logout to iTop's logoff page) and `librechat` (with the post-logout redirect URI), email lock-down, test users. An existing client is merged, not replaced: settings the setup does not own stay | `client/keycloak_realm.py` (admin REST API, the manual's values) | example, Keycloak sections |
| LibreChat `.env` (Keycloak login and logout) and `librechat.yaml` | `librechat/` | example, "LibreChat" |
| Check lists, one file per check group (see [Check groups](#check-groups)) | `client/groups/*.py`, run by `client/checks.py` | both "Check list" sections |
| User switch in one browser: A connects iTop and logs out, B logs in and connects; B must consent and get a token as B. Runs as the last check of the group `librechat`; `python user_switch.py` prints each step | `client/user_switch.py` | example, check 8 |
| nginx in front of the MCP server, also under a path prefix (nginx variant only) | `compose.nginx.yaml`, `nginx/start.sh` | README, "Reverse proxy (TLS)" |

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

LibreChat needs a model with tool calls for check 7. The test stack uses the shared LiteLLM endpoint. Put your key, the endpoint's base URL and the model into
`test-stack/llm.env`, which is git-ignored and never committed:

```sh
umask 077
printf 'LITELLM_KEY=<your key>
LITELLM_BASE_URL=<base URL of the endpoint>
LITELLM_MODEL=<model>
' > llm.env
docker compose up -d librechat        # pick up the key
```

To use a key file somewhere else, set `LLM_ENV_FILE` to its path when you start the stack and
run the checks; compose reads it in place. On the test VM, `scripts/stack-on-vm.sh` does this with
the shared key `/root/shared/llm.env` (see [test-vm.md](../docs/agents/test-vm.md#llm-key)).

The default is the `LiteLLM` endpoint of `librechat/librechat.yaml`: key, base URL and model come from `LITELLM_KEY`,
`LITELLM_BASE_URL` and `LITELLM_MODEL`; on the test VM the shared key file `/root/shared/llm.env` has them. For
another provider, change the endpoint in `librechat/librechat.yaml` and the variable names in `llm.env`. A chat
check that gets an empty answer retries once and says so. Without `LITELLM_KEY`, `checks.py` reports the chat
checks as SKIP ("no shared LLM key"), and SKIPs do not fail the run.

## nginx as TLS proxy

The stack normally runs Caddy as TLS proxy. The nginx variant replaces it with nginx 1.30.8, with
the same hostnames and certificates, and tests the nginx blocks of the
[README](../README.md#reverse-proxy-tls). Run it on demand; it is **mandatory before a release**
(see "Releasing" in the README).

```sh
cd test-stack
./make-certs.sh
docker compose -f compose.yaml -f compose.nginx.yaml up -d --build
docker compose -f compose.yaml -f compose.nginx.yaml logs -f setup     # wait for "setup complete"
docker compose -f compose.yaml -f compose.nginx.yaml run --rm client python checks.py
```

Use both files for every command of this variant. Without `compose.nginx.yaml` the stack runs with
Caddy as before. To switch an existing stack, `up -d` with the other set of files is enough; the
volumes stay.

- At start-up, `nginx/start.sh` takes the two nginx code blocks of the README section "Reverse
  proxy (TLS)" and builds the server block of `mcp.example.com` from them: the proxy in front of the
  MCP server, with the path-prefix locations inside it. It fills in only what the README leaves to
  the reader: the upstream (`127.0.0.1:8130` becomes `mcp:8130`, and `mcp-prefix:8130` for the
  prefix) and the certificate paths. The generated file is printed in `docker compose logs proxy`.
- If a block is missing or nginx refuses it, the proxy does not start and the check list fails. A
  block that starts but forwards wrongly fails the checks.
- `mcp-prefix` is a second MCP server with `MCP_RESOURCE_URL=https://mcp.example.com/itop-mcp/mcp`.
  The check "README: MCP server and its metadata under a path prefix" runs only in this variant:
  401 with the prefixed metadata URL, the metadata itself, and whoami with a token. The token comes
  from the normal OAuth flow; the server does not check the token's resource.
- `itop.example.com`, `sso.example.com` and `chat.example.com` are plain proxy blocks of the stack
  (`nginx/stack.conf`). iTop itself stays on Apache.

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

## LibreChat's login limit

LibreChat limits logins per IP. It counts every request under `/oauth/`: the start and the callback
of a login (two per login), and also the "connected" page after an MCP server's OAuth callback (the
checks do not open it). Its settings are `LOGIN_MAX` requests per `LOGIN_WINDOW` minutes, by default
7 per 5, in a fixed window that starts with the first request. Over the limit LibreChat answers
`auth_rate_limited`. The check group `librechat` logs into LibreChat five times (ten requests), so with
LibreChat's default a single run already reaches the limit and a second run right after it would too.

- **The setting**: the test stack sets `LOGIN_MAX` on the `librechat` service from
  `TEST_LIBRECHAT_LOGIN_MAX`, **100 by default** (`compose.yaml`). That is enough for many check runs in
  one window. `LOGIN_WINDOW` keeps LibreChat's 5 minutes. The setting is in `compose.yaml`, not in
  `librechat/librechat.env`, because that file follows the example setup, and
  `docs/setup/example-keycloak-librechat.md` keeps LibreChat's normal limit: a real install should not
  raise it. To try the checks with the normal limit:
  `TEST_LIBRECHAT_LOGIN_MAX=7 docker compose up -d librechat` (recreates only LibreChat).
- **When a check still hits it** (normal limit, or another client on the same IP): before a login the
  checks look at LibreChat's `X-RateLimit-Remaining`; when the budget is used up they wait for the window
  to end (`X-RateLimit-Reset`) and go on. When LibreChat answers `auth_rate_limited` anyway, they wait for
  the window and try the login once more. Refused again, the check reports **SKIP** with the reason, and
  so do the checks that need that login; the limit never makes a check FAIL. A wait shows in the check's
  line (`waited N s for LibreChat's login limit`) and makes that run up to five minutes longer.
- **Reset**: LibreChat keeps the count in memory, so restarting it starts a new window:
  `docker compose restart librechat` (with `-p $RUN` on the VM). The checks wait until it answers again.

## Notes

- LibreChat's login limit: see [LibreChat's login limit](#librechats-login-limit).
- Checks for the LibreChat logout: the Keycloak setup run again keeps an attribute, a redirect URI and
  a post-logout redirect URI that another setup put on the `librechat` client; after `bob` logs out of
  LibreChat, Keycloak ends the session, the browser lands on LibreChat's login page, and **Sign in
  with Keycloak** shows Keycloak's login form again so that `anna` can log in (check 8 of the example).
- The stack uses the names `itop-mcp-test-*` for its project, images and volumes.
  On a shared Docker host give each run its own project name and image tag, e.g.
  `TEST_TAG=ic07 docker compose -p ic07 up -d --build` (see `docs/agents/test-vm.md`); without
  `TEST_TAG` the images keep their fixed names.
- On the test VM, `scripts/stack-on-vm.sh` does a whole run with its own project name and image
  tags, from start to clean-up (see `docs/agents/test-vm.md`).
