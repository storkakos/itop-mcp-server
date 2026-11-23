# iTop prerequisites

**Required for every customer.** This manual prepares an existing iTop so that it can act as the
**authorization server** for the MCP server: iTop logs the user in, asks for consent, and issues the
access token that the MCP client sends to the MCP server. The MCP server only forwards that token to
iTop's REST/JSON API. It stores no user secrets and issues no tokens.

The MCP server needs only the altioo-oauth-server extension. Logging into iTop through an
**identity provider** (for example Keycloak) is optional: it needs the combodo-hybridauth extension
and its two helper extensions, which this manual lists and installs alongside, marked *only with an
identity provider*. How to connect hybridauth to Keycloak is described in
[the example setup](example-keycloak-librechat.md). Without an identity provider, users log in with
iTop's own login form, and everything in this manual still works.

## Contents

1. [Example hostnames](#example-hostnames)
2. [Requirements](#requirements)
3. [Extensions](#extensions)
4. [Install the extensions](#install-the-extensions)
5. [Configure iTop](#configure-itop)
6. [Web server rewrites](#web-server-rewrites)
7. [Licences](#licences)
8. [Check list](#check-list)

## Example hostnames

All URLs use HTTPS behind the customer's reverse proxy. Replace them with yours everywhere in this
manual and in the config snippets.

| Example | What it is | Replace with yours |
|---|---|---|
| `https://itop.example.com` | iTop (`ITOP_BASE_URL` of the MCP server) | |
| `https://itop.example.com/env-production/altioo-oauth-server` | Issuer of the authorization server (derived from the iTop URL) | |
| `https://mcp.example.com/mcp` | Public URL of the MCP server (`MCP_RESOURCE_URL`) | |
| `https://chat.example.com/api/mcp/itop/oauth/callback` | Callback of the MCP client (LibreChat in the example setup; another client shows its own) | |

## Requirements

| | |
|---|---|
| iTop | **3.2.1 or later**, already installed (minimum required by altioo-oauth-server). For a fresh installation see [Fresh installation](#fresh-installation). |
| iTop module | `authent-token` 2.2.1 or later (ships with iTop) |
| HTTPS | Required for iTop and the MCP server. OAuth over plain HTTP exposes every code and token. |
| Cron | iTop's `webservices/cron.php` running. altioo-oauth-server cleans up expired connections hourly; without cron, an expired connection keeps its token until the client next tries to refresh it. |
| Web server | Apache with `mod_rewrite` and `AllowOverride All` for the extension's directory, or nginx with the rules in [Web server rewrites](#web-server-rewrites) |
| Reverse proxy | If iTop runs behind a reverse proxy, the web server must pass the caller's address to PHP (Apache `mod_remoteip`, nginx `real_ip`). Otherwise the extension's log and its registration rate limit see only the proxy's address. If the proxy terminates TLS, PHP must also see the public scheme, host and port, see [PHP behind a reverse proxy](#php-behind-a-reverse-proxy). Otherwise users land on iTop's home page after login instead of the consent page. |

### Tested with

| Component | Version | Validation run |
|---|---|---|
| iTop | 3.2.3 | 2026-11-23 |
| altioo-oauth-server | 0.1.0 | 2026-11-23 |
| combodo-hybridauth (only with an identity provider) | 2.1.1 | 2026-11-23 |
| combodo-oauth2-client (only with an identity provider; ships with iTop 3.2.3) | 1.0.9 | 2026-11-23 |
| itop-attribute-encrypted-password (only with an identity provider; ships with iTop 3.2.3) | 1.1.1 | 2026-11-23 |

The validation run used Apache 2.4 with mod_php 8.3 behind a TLS-terminating reverse proxy.

Newer versions should work but are untested.

With an identity provider, use **iTop 3.2.3 or later**: Combodo's
[hybridauth documentation](https://www.itophub.io/wiki/page?id=extensions:combodo-hybridauth) names
iTop 3.2.3 as the minimum for the extension. *To be checked:* whether hybridauth 2.1.1 also runs on
iTop 3.2.1 and 3.2.2; until then, treat 3.2.3 as the minimum for that path.

## Extensions

Download from the vendor and check the SHA256 before installing.

| Extension | Version | Download | SHA256 | Licence |
|---|---|---|---|---|
| altioo-oauth-server | `v0.1.0` | [altioo-oauth-server-0.1.0.zip](https://github.com/AltiooBV/altioo-oauth-server/releases/download/v0.1.0/altioo-oauth-server-0.1.0.zip) | `d8933b65e2250d029238923efc0a4acff4b80a099b815a43dad97a0d30b6e320` | [AGPL-3.0-or-later](https://github.com/AltiooBV/altioo-oauth-server/blob/v0.1.0/LICENSE) |

**Only with an identity provider** (login to iTop through Keycloak or another OpenID Connect
provider). combodo-hybridauth depends on combodo-oauth2-client (which ships the HybridAuth library,
including its Keycloak adapter), and that depends on itop-attribute-encrypted-password. Download
only combodo-hybridauth. The other two ship with iTop 3.2.3 in `datamodels/2.x/`
(combodo-oauth2-client 1.0.9, itop-attribute-encrypted-password 1.1.1) and are installed with every
iTop 3.2.3, even without hybridauth; do **not** copy them into `extensions/` as well, or iTop finds
the same module twice.

| Extension | Version | Download | SHA256 | Licence |
|---|---|---|---|---|
| combodo-hybridauth | `2.1.1` | [2.1.1.zip](https://github.com/Combodo/combodo-hybridauth/archive/refs/tags/2.1.1.zip) | `5ddb33cc94669d65e540d51a484a56fc7b5a38bfe8f73f8709d217653d6ab3e6` | [Combodo Software License](https://www.combodo.com/documentation/combodo-software-license.html) |

This is a GitHub tag archive. GitHub generates it on download; its hash has been stable in
practice, but GitHub does not guarantee it. If the hash does not match, compare the contents with
the tag on GitHub before you install. The extension is also available from Combodo's
[iTop Hub](https://store.itophub.io/), which may ship a different packaging.

Check the download:

```sh
sha256sum altioo-oauth-server-0.1.0.zip
```

```powershell
Get-FileHash altioo-oauth-server-0.1.0.zip -Algorithm SHA256
```

The vendor's README in the ZIP (`README.md`) describes every setting in detail. This manual covers
only what the MCP server needs. For hybridauth, Combodo's
[extension documentation](https://www.itophub.io/wiki/page?id=extensions:combodo-hybridauth) lists
all settings.

## Install the extensions

These steps upgrade an existing iTop. Install all extensions you need in one run of the wizard. Plan a short maintenance window: the setup wizard recompiles
iTop.

### 1. Back up

Back up the iTop database and `conf/production/config-itop.php`. The setup wizard keeps the existing
configuration values and only fills in missing keys, but if it cannot parse the configuration file
it starts with a blank one. A backup of the whole iTop directory is safest, because setup rewrites
`env-production/`.

### 2. Copy the extensions

Unpack the ZIP into iTop's `extensions/` folder so that `extensions/altioo-oauth-server/README.md`
exists. Make sure the web server user can read the files.

**Only with an identity provider:** the GitHub tag archive unpacks into a folder with the version
in its name (`combodo-hybridauth-2.1.1/`). Rename the folder to the extension's name, so that this
file exists:

```
extensions/combodo-hybridauth/module.combodo-hybridauth.php
```

The folder name matters: hybridauth's callback URL, which you register in the identity provider,
is built from it (`https://itop.example.com/env-production/combodo-hybridauth/landing.php`).
Check that iTop's own copies of the two helper modules exist:

```
datamodels/2.x/combodo-oauth2-client/module.combodo-oauth2-client.php
datamodels/2.x/itop-attribute-encrypted-password/module.itop-attribute-encrypted-password.php
```

They contain their `vendor/` libraries; no Composer run is needed.

Copying alone changes nothing: iTop runs the compiled copy in `env-production/`, which the setup
wizard creates in step 4.

### 3. Make the configuration file writable for the wizard

iTop keeps `conf/production/config-itop.php` read-only (mode `0440`). The setup wizard refuses an
upgrade while it is: it stops with "the configuration file 'conf/production/config-itop.php' already
exists and cannot be overwritten". Make it writable for the web server user, which owns it:

```sh
chmod u+w /var/www/itop/conf/production/config-itop.php
```

On Windows, clear the read-only attribute in the file's properties, or:

```powershell
attrib -R C:\inetpub\itop\conf\production\config-itop.php
```

### 4. Run the setup wizard as an upgrade

1. Open `https://itop.example.com/setup/`, log in as an administrator, and choose **Upgrade an
   existing iTop instance**.
2. In the last extensions step ("Select additional extensions to install"), **tick Altioo OAuth
   Server** (altioo-oauth-server). On an upgrade, new extensions are **not** ticked by default. If
   you skip this, the extension is not installed and nothing below works.
   **Only with an identity provider:** also tick **oAuth/OpenID authentication**. That is
   combodo-hybridauth: it has no `extension.xml`, so the wizard shows it as its own checkbox under
   its module label, and it is not ticked either. combodo-oauth2-client and
   itop-attribute-encrypted-password get no checkbox: they are hidden modules that iTop selects
   automatically and that a standard iTop 3.2.3 already has installed. The wizard's summary lists
   them as "Oauth2 Client (hidden)" and "Encrypted password iTop attribute (hidden)". If it reports
   a missing dependency instead, check the folder name and the two `datamodels/2.x/` paths from
   step 2.
3. Finish the wizard. It adds three tables (`priv_altioo_oauth_client`, `priv_altioo_oauth_grant`,
   `priv_altioo_oauth_code`). Its last page shows "Manual operations required" with a link to the
   altioo-oauth-server README; the steps that matter for the MCP server are the rest of this manual.

With hybridauth ticked, the wizard also writes a `combodo-hybridauth` block with the extension's
defaults into the configuration file. [The example setup](example-keycloak-librechat.md#combodo-hybridauth-in-mymodulesettings)
replaces it.

### 5. Make the configuration file writable for the edit

When the wizard finishes, iTop makes `config-itop.php` read-only again. Make it writable for the
edit in [Configure iTop](#configure-itop), check it, and make it read-only again afterwards:

```sh
chmod u+w /var/www/itop/conf/production/config-itop.php
# ... edit as described in "Configure iTop" ...
php -l /var/www/itop/conf/production/config-itop.php   # syntax check, must print "No syntax errors"
chmod 0440 /var/www/itop/conf/production/config-itop.php
```

On Windows, clear and set the read-only attribute in the file's properties, or:

```powershell
attrib -R C:\inetpub\itop\conf\production\config-itop.php
# ... edit, then check with php -l ...
attrib +R C:\inetpub\itop\conf\production\config-itop.php
```

Always run `php -l` before you make the file read-only again: a configuration file with a syntax
error takes iTop down.

### Fresh installation

For a new iTop, follow the [iTop installation guide](https://www.itophub.io/wiki/page?id=latest:install:start)
with the extensions already in `extensions/`, tick them in the extension step, then continue with
[Configure iTop](#configure-itop).

## Configure iTop

All settings go into `conf/production/config-itop.php`. Change existing keys rather than adding a
second copy of them. Keep settings you already have that are not mentioned here.

### Profiles: who may use the assistant

The assistant can read everything the user's own iTop account can read, because the MCP server calls
iTop with that user's token. Two settings decide who gets such a token:

| Setting | Decides | Applies to |
|---|---|---|
| `authent-token` → `personal_tokens_allowed_profiles` | Who may own **any** personal token in iTop: tokens made by hand under *My Account* and tokens issued through OAuth for any resource | Personal tokens in general |
| `altioo-oauth-server` → `resources` → `itop-mcp` → `required_profiles` | Who may connect **this resource** (the MCP server) through OAuth. Anyone else is refused before the consent page. | The MCP server only |

Set both to the profiles that should use the assistant, for example `Service Desk Agent` and
`Support Agent`. Use the profile names exactly as they appear in your iTop.

**Leave `Administrator` out.** An administrator's token lets the assistant read everything an
administrator can see, including all organizations, users and configuration items. If an
administrator also needs the assistant, give them a second, non-admin account with an agent profile.

If `personal_tokens_allowed_profiles` already lists profiles for other uses (for example REST
integrations with hand-made tokens), keep them there, and restrict the assistant through
`required_profiles` only.

### Settings in `$MySettings`

```php
$MySettings = array(
	// ... existing settings ...

	// Keep the login types you already use and add "token".
	// The first entry is the default login page; "form" first keeps iTop's own login form.
	'allowed_login_types' => 'form|token',
	// With an identity provider, also add "hybridauth-<provider>", where <provider> is the key
	// under combodo-hybridauth → providers (case-sensitive). For the Keycloak example setup:
	// 'allowed_login_types' => 'form|token|hybridauth-Keycloak',

	// Lets a personal token call REST/JSON without the "REST Services User" profile.
	'allow_rest_services_via_tokens' => true,
);
```

### Settings in `$MyModuleSettings`

```php
$MyModuleSettings = array(
	// ... existing module settings ...

	'authent-token' => array(
		// Only the profiles that should use the assistant. No Administrator (see above).
		'personal_tokens_allowed_profiles' => array('Service Desk Agent', 'Support Agent'),
		// Shows "Personal Tokens" under My Account, where users see and end their connections.
		'enable_myaccount_menu' => true,
	),

	'altioo-oauth-server' => array(
		// The MCP client's callback, exactly as the client sends it. This list replaces the
		// extension's defaults (Claude, ChatGPT, ...), so only the clients you list here can connect.
		'redirect_uris' => array(
			'https://chat.example.com/api/mcp/itop/oauth/callback',
		),
		// Callbacks on localhost/127.0.0.1 are for local tests only. Keep false in production.
		'allow_loopback' => false,

		'access_token_lifetime' => 3600, // seconds
		'grant_idle_days' => 30,
		'max_grant_days' => 90,

		// Setting "resources" replaces the extension's defaults (altioo-mcp and REST/JSON).
		'resources' => array(
			'itop-mcp' => array(
				// EXACTLY the MCP server's MCP_RESOURCE_URL: same scheme, host, port, path,
				// no trailing slash unless MCP_RESOURCE_URL has one.
				'url' => 'https://mcp.example.com/mcp',
				'label' => 'iTop assistant',
				'scope_prefix' => 'REST/JSON',
				'default_scopes' => array('REST/JSON'),
				'bearer_methods' => array('header'),
				// Same profiles as personal_tokens_allowed_profiles above. No Administrator.
				'required_profiles' => array('Service Desk Agent', 'Support Agent'),
			),
		),
	),
);
```

Notes on the values:

- **`url`** is compared character by character with the `resource` the MCP client asks for, which
  it takes from the MCP server's metadata, which comes from `MCP_RESOURCE_URL`. If they differ, the
  iTop page says "Unknown resource" and the OAuth flow fails. This is the most common setup error.
- **`scope_prefix`/`default_scopes` `REST/JSON`**: the MCP server calls iTop's REST/JSON API with
  the token, so the token needs this scope. The MCP server also requires it.
- **`bearer_methods` `header`**: the MCP client sends the token as `Authorization: Bearer`.
- **`redirect_uris`**: if the MCP client cannot register, iTop's error log (channel
  `altioo-oauth-server`) names the callback it asked for. Add it exactly as logged, if the host is
  your client's.

### Which tokens the MCP server accepts

The MCP server accepts every token that iTop's REST/JSON API accepts. It does **not** check which
resource a token was issued for. altioo-oauth-server records that (each connection stores its
resource), but it offers it only as a PHP API inside iTop (`TokenAudience`, see its README). The
tokens are opaque iTop personal tokens, altioo has no introspection endpoint, and the connection
records are readable by administrators only, so the MCP server cannot ask. (Checked against
altioo-oauth-server 0.1.0.)

So a token issued through altioo for another entry in `resources`, or a personal token made by hand
under *My Account* with the `REST/JSON` scope, also works at the MCP server. It gets no more rights
there than it already has on `rest.php` directly, and the MCP server only reads. To keep the
assistant to the people meant for it:

- keep `resources` to the single `itop-mcp` entry above, and
- keep `personal_tokens_allowed_profiles` to the profiles that should use the assistant.

### Token lifetimes

| Setting | Value | What it means for the user |
|---|---|---|
| `access_token_lifetime` | 3600 s (1 hour) | The MCP client renews the token every hour in the background. The user notices nothing. Disabling an iTop user stops their assistant access at the latest one hour later. |
| `grant_idle_days` | 30 days | If the user does not use the assistant for 30 days, the connection ends and they log in and consent again. |
| `max_grant_days` | 90 days | Every connection ends 90 days after it was made, even if used daily. The user then logs in and consents again. This bounds how long a connection outlives an offboarding that misses the iTop user. |

Users see their connections under *My Account* → *Personal Tokens* → *Connected applications* and
can end them there. Administrators see all of them under *Admin tools* → *OAuth connections*.

## Web server rewrites

MCP clients look for the authorization server's metadata at the **site root** with the issuer path
appended (RFC 8414), for example
`https://itop.example.com/.well-known/oauth-authorization-server/env-production/altioo-oauth-server`.
An iTop extension cannot answer there, so the web server must rewrite these paths to the extension.

The MCP server publishes its own protected-resource metadata (RFC 9728) itself; iTop needs no rule
for it.

### Apache

In the iTop vhost, with `mod_rewrite` enabled (rule from the altioo-oauth-server README):

```apache
RewriteEngine On
# Authorization server metadata (RFC 8414) and its OpenID Connect twin, at the site root
RewriteRule ^/?\.well-known/(oauth-authorization-server|openid-configuration)/env-production/altioo-oauth-server$ /env-production/altioo-oauth-server/index.php?route=$1 [PT,QSA,L]
```

The extension's own `.htaccess` needs `AllowOverride All` for its directory. It allows only
`index.php` and the two `.well-known` paths inside the extension, and denies everything else
(`src/`, `vendor/`, ...).

### nginx

nginx ignores the extension's `.htaccess`, so add both the rewrite and the deny rule to the iTop
`server` block:

```nginx
# Authorization server metadata (RFC 8414) and its OpenID Connect twin, at the site root
location ~ ^/\.well-known/(oauth-authorization-server|openid-configuration)/env-production/altioo-oauth-server$ {
	rewrite ^ /env-production/altioo-oauth-server/index.php?route=$1 last;
}

# The same metadata inside the issuer path
location ~ ^/env-production/altioo-oauth-server/\.well-known/(oauth-authorization-server|openid-configuration)$ {
	rewrite ^ /env-production/altioo-oauth-server/index.php?route=$1 last;
}

# Everything else in the extension's directory except index.php is private
location ^~ /env-production/altioo-oauth-server/ {
	location = /env-production/altioo-oauth-server/index.php {
		# same PHP handling as the rest of iTop, e.g.:
		include fastcgi_params;
		fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
		fastcgi_pass php-fpm;
	}
	return 404;
}
```

Adjust `fastcgi_pass` to your PHP-FPM upstream.

### PHP behind a reverse proxy

When a reverse proxy terminates TLS and talks plain HTTP to iTop's web server, PHP sees `http`
and port 80. After a login, iTop sends the user back to the page they came from (here: the
altioo-oauth-server authorization page) only if that page's URL, as PHP sees it, starts with
`app_root_url`. Otherwise it sends them to its home page, and the OAuth flow stops there. Two parts
of iTop check this differently, and both must see the public URL:

- iTop's own login (form and the redirect after choosing a login method) uses `HTTPS`,
  `SERVER_NAME` and `SERVER_PORT`.
- hybridauth (only with an identity provider) uses `REQUEST_SCHEME` and `HTTP_HOST`.

The proxy must pass the public `Host` header and `X-Forwarded-Proto: https`.

**Apache** (tested), in the iTop vhost that the proxy talks to:

```apache
# Public scheme, host and port, as clients see them
ServerName https://itop.example.com:443
UseCanonicalName On
# HTTPS=on for PHP when the proxy says the client used HTTPS
SetEnvIf X-Forwarded-Proto "^https$" HTTPS=on
```

`ServerName` with scheme and `UseCanonicalName On` give PHP `REQUEST_SCHEME=https` and
`SERVER_PORT=443`; `SetEnvIf` gives it `HTTPS=on`. `ServerName https://itop.example.com` alone is
not enough. Only use `SetEnvIf` on `X-Forwarded-Proto` when the web server is reachable through the
proxy only.

**nginx** (not tested), in the `location` that passes PHP to PHP-FPM:

```nginx
fastcgi_param HTTPS on;
fastcgi_param REQUEST_SCHEME https;
fastcgi_param SERVER_PORT 443;
fastcgi_param SERVER_NAME itop.example.com;
```

To check what PHP sees, log in through the OAuth flow (check 5 of the [check list](#check-list)):
after the login, the browser must show the consent page, not iTop's home page.

### Other web servers

Rewrite `/.well-known/oauth-authorization-server/env-production/altioo-oauth-server` and
`/.well-known/openid-configuration/env-production/altioo-oauth-server` internally to
`/env-production/altioo-oauth-server/index.php?route=oauth-authorization-server` and
`?route=openid-configuration`, and deny everything under `env-production/altioo-oauth-server/` except
`index.php`. On IIS the extension's `web.config` covers the deny part; it needs the URL Rewrite
module.

## Licences

This repository does not contain or redistribute any iTop extension. The customer obtains each
extension from its vendor, under that vendor's licence, and is responsible for complying with its
terms.

| Extension | Vendor | Licence |
|---|---|---|
| altioo-oauth-server | [Altioo BV](https://github.com/AltiooBV/altioo-oauth-server) | [GNU AGPL-3.0-or-later](https://github.com/AltiooBV/altioo-oauth-server/blob/v0.1.0/LICENSE) |
| combodo-hybridauth (only with an identity provider) | [Combodo](https://github.com/Combodo/combodo-hybridauth) | [Combodo Software License](https://www.combodo.com/documentation/combodo-software-license.html), as stated in the extension's source files; the repository has no licence file |
| combodo-oauth2-client (only with an identity provider) | [Combodo](https://github.com/Combodo/combodo-oauth2-client) | AGPL-3.0, as stated in the module file; it bundles the [HybridAuth](https://hybridauth.github.io/license.html) library under its own permissive licence (`vendor/hybridauth/hybridauth/COPYING.md`) |
| itop-attribute-encrypted-password (only with an identity provider) | [Combodo](https://github.com/Combodo/itop-attribute-encrypted-password) | AGPL-3.0, as stated in the module file |

iTop itself is licensed by Combodo under the AGPL-3.0 (community edition) or a commercial licence.

## Check list

Run these after the MCP server is started with `ITOP_BASE_URL=https://itop.example.com` and
`MCP_RESOURCE_URL=https://mcp.example.com/mcp`. Each check builds on the one before; fix a failing
check before you go on.

### 1. The authorization server metadata answers at the site root

```sh
curl -s https://itop.example.com/.well-known/oauth-authorization-server/env-production/altioo-oauth-server
```

**Expected:** JSON with
`"issuer":"https://itop.example.com/env-production/altioo-oauth-server"` and the endpoints
`authorization_endpoint`, `token_endpoint` and `registration_endpoint`.

**If not:**

| Result | Fix |
|---|---|
| 404 | The rewrite rule is missing or not active. Check [Web server rewrites](#web-server-rewrites), and that `mod_rewrite` is loaded. |
| 404 also for `https://itop.example.com/env-production/altioo-oauth-server/.well-known/openid-configuration` | The extension is not installed: run the setup wizard again and tick it. |
| 403 | `AllowOverride` is off for the extension's directory (Apache), or the deny rule is too broad (nginx). |
| iTop login page or HTML | The rewrite points to the wrong path. |
| `issuer` with `http://` or another host | iTop's `app_root_url` in `config-itop.php` does not match the public URL. Set it to `https://itop.example.com/`. |

### 2. The MCP server answers 401 and points to its metadata

```sh
curl -si -X POST https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

**Expected:** `HTTP/1.1 401` (or `HTTP/2 401` behind a proxy with HTTP/2) and a header like

```
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
```

**If not:**

| Result | Fix |
|---|---|
| 502/504 | The reverse proxy cannot reach the MCP server container. |
| `resource_metadata` with another host or `http://` | `MCP_RESOURCE_URL` is not the public URL. Set it to exactly the URL clients use. |

This check cannot catch a proxy that rewrites the `Host` header: without a token, the server
answers `401` before it looks at the host. A wrong `Host` shows up only after login, as
`421 Misdirected Request` on tool calls (see check 5).

### 3. The protected-resource metadata points at iTop

Use the URL from `resource_metadata` in check 2:

```sh
curl -s https://mcp.example.com/.well-known/oauth-protected-resource/mcp
```

**Expected:**

```json
{
  "resource": "https://mcp.example.com/mcp",
  "authorization_servers": ["https://itop.example.com/env-production/altioo-oauth-server"],
  "scopes_supported": ["REST/JSON"],
  "bearer_methods_supported": ["header"]
}
```

`authorization_servers` must be the `issuer` from check 1, character by character.

**If not:**

| Result | Fix |
|---|---|
| 404 | The reverse proxy forwards only `/mcp`. It must also forward `/.well-known/oauth-protected-resource/mcp` to the MCP server. |
| `authorization_servers` differs from the `issuer` | `ITOP_BASE_URL` (or `ITOP_OAUTH_ISSUER`, if set) on the MCP server does not match iTop's public URL. |

### 4. The resource URL matches in all three places

These three values must be identical, character by character:

| Where | Value |
|---|---|
| MCP server environment | `MCP_RESOURCE_URL` |
| Check 3 | `"resource"` |
| `config-itop.php` | `altioo-oauth-server` → `resources` → `itop-mcp` → `url` |

**If they differ:** the OAuth flow starts, the user logs into iTop, and the iTop page then says
**"Unknown resource"**. This is the most likely cause of a failing OAuth flow. Typical differences: a
trailing slash, `http` vs `https`, an explicit `:443`, an internal host name instead of the public
one. Fix `config-itop.php` to match `MCP_RESOURCE_URL`.

### 5. An MCP client can connect

Add `https://mcp.example.com/mcp` to the MCP client and connect. The client sends the user to iTop's
login page, then to a consent page naming the client and "iTop assistant". After consent, the
assistant's tools work.

| Symptom | Fix |
|---|---|
| The client cannot register | Its callback is not in `redirect_uris`. iTop's error log (channel `altioo-oauth-server`) names the URI it asked for. |
| "Unknown application" on the iTop page | Same as above, or the client registered more than 24 hours ago without completing a connection; connect again. |
| After the login you land on iTop's home page instead of the consent page | PHP does not see the public URL behind the reverse proxy. See [PHP behind a reverse proxy](#php-behind-a-reverse-proxy), then connect again. |
| "Personal tokens not allowed" | The user's profiles are not in `personal_tokens_allowed_profiles`. |
| The user is refused before the consent page | The user has none of the `required_profiles`. |
| Login and consent work, but the client never shows "Connected" and keeps asking to connect; `docker logs` shows `Token abgelehnt` | `token` is missing from `allowed_login_types`, or `allow_rest_services_via_tokens` is not `true`. The server checks every request's token with a REST call, so every request gets `401`. |
| Connected, but tool calls fail with `421 Misdirected Request` | The reverse proxy does not pass the public `Host` header, or `MCP_RESOURCE_URL` names another host. |
| "Unknown resource" | See check 4. |

For more detail, raise the extension's log level in `config-itop.php` with
`'log_level_min' => array('altioo-oauth-server' => 'Debug')` in `$MySettings` and read
`log/error.log`.
