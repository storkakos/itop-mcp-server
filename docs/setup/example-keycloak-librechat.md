# Example setup: Keycloak and LibreChat

**Example setup, not required.** This manual shows one documented way to connect an
**identity provider** (Keycloak) and an **MCP client** (LibreChat) to iTop and the MCP server. Other
identity providers and MCP clients work too; [the iTop prerequisites](itop-prerequisites.md) stay
the same for them.

Before you start:

- Follow [the iTop prerequisites](itop-prerequisites.md) completely, including the extensions marked
  *only with an identity provider* (combodo-hybridauth and its two helper extensions), and make sure
  checks 1 to 4 of its check list pass.
- Keycloak is installed and reachable over HTTPS, with a realm for your users. Installing Keycloak
  is not covered; see the [Keycloak documentation](https://www.keycloak.org/documentation).

<!-- Ticket 03 (LibreChat) adds the LibreChat prerequisites here (installed LibreChat, links to
     the LibreChat docs for installation, MongoDB and LLM setup). -->

## Contents

1. [Example hostnames](#example-hostnames)
2. [Who does what](#who-does-what)
3. [Tested with](#tested-with)
4. [Keycloak: client for iTop](#keycloak-client-for-itop)
5. [iTop: log in with Keycloak](#itop-log-in-with-keycloak)
6. [iTop user accounts](#itop-user-accounts)
7. [Check list](#check-list)

<!-- Ticket 03 adds its sections (Keycloak client for LibreChat, LibreChat configuration) between
     "iTop user accounts" and "Check list", and adds them to this list. -->

## Example hostnames

All URLs use HTTPS behind the customer's reverse proxy. Replace them with yours everywhere in this
manual and in the config snippets.

| Example | What it is | Replace with yours |
|---|---|---|
| `https://itop.example.com` | iTop | |
| `https://sso.example.com` | Keycloak, base URL without `/realms/...` | |
| `example` | Keycloak realm of your users | |
| `https://sso.example.com/realms/example` | Issuer of the realm (derived from the two lines above) | |
| `https://itop.example.com/env-production/combodo-hybridauth/landing.php` | hybridauth's callback in iTop (derived from the iTop URL) | |
| `https://chat.example.com` | LibreChat | |
| `https://mcp.example.com/mcp` | Public URL of the MCP server (`MCP_RESOURCE_URL`) | |

## Who does what

| Component | Role | What it does in this setup |
|---|---|---|
| Keycloak | **Identity provider** | Logs users in: into iTop (through hybridauth) and into LibreChat (through OpenID Connect). |
| iTop with altioo-oauth-server | **Authorization server** | Asks the logged-in user for consent and issues the access token for the MCP server. Checks the token on every REST call. |
| LibreChat | **MCP client** | The chat users work in. Fetches the token from iTop and sends it with every call to the MCP server. |
| MCP server | **MCP server** | Forwards each tool call to iTop's REST/JSON API with the caller's token. Stores no secrets, issues no tokens. |

**Keycloak never issues MCP tokens.** The tokens Keycloak issues log users into iTop and LibreChat,
nothing more. The MCP server's metadata names iTop as its only authorization server, and iTop
accepts only tokens it issued itself. Do not try to configure Keycloak as the authorization server
of the MCP server, and do not add an audience or client scope for the MCP server in Keycloak.

What a user experiences the first time they connect the assistant:

1. The user logs into LibreChat with Keycloak.
2. They connect the iTop server in LibreChat. LibreChat calls the MCP server, gets `401`, reads the
   metadata, and sends the user's browser to iTop's authorization page.
3. iTop needs a logged-in user and shows its login page. The user clicks **Sign in with Keycloak**.
   If they still have a Keycloak session from step 1, Keycloak lets them through without asking for
   a password again.
4. Keycloak sends the browser back to iTop (`landing.php`). iTop logs the user in as the iTop user
   that matches their email (see [iTop user accounts](#itop-user-accounts)) and shows the
   altioo-oauth-server consent page.
5. After consent, iTop issues the token to LibreChat. From now on, the assistant sees exactly what
   this iTop user may see.

## Tested with

| Component | Version | Validation run |
|---|---|---|
| iTop | 3.2.3 | pending |
| combodo-hybridauth | 2.1.1 | pending |
| Keycloak | 26.8.2 | pending |

<!-- Ticket 03 adds the LibreChat row (v0.8.9). -->

Newer versions should work but are untested.

## Keycloak: client for iTop

iTop logs users in through a **confidential** OpenID Connect client named `itop` in the realm
`example`. In the Keycloak admin console (Keycloak 26):

1. Select the realm `example`.
2. Go to **Clients** → **Create client**.
3. Fill in the three pages of the wizard with the values below, then **Save**.
4. Open the **Credentials** tab of the new client. Leave **Client Authenticator** at
   **Client Id and Secret** and copy the **Client Secret**. You need it in
   [iTop: log in with Keycloak](#itop-log-in-with-keycloak).

| Page | Field | Value |
|---|---|---|
| General settings | Client type | `OpenID Connect` |
| | Client ID | `itop` |
| | Name | `iTop` |
| Capability config | Client authentication | **On** (confidential client) |
| | Authorization | Off |
| | Standard flow | **On** |
| | Direct access grants | **Off** (on by default when the client is created; untick it) |
| | Implicit flow | Off |
| | Service accounts roles | Off |
| | Standard Token Exchange | Off |
| | OAuth 2.0 Device Authorization Grant | Off |
| | OIDC CIBA Grant | Off |
| | PKCE method | empty (see below) |
| Login settings | Root URL | `https://itop.example.com` |
| | Home URL | `https://itop.example.com/` |
| | Valid redirect URIs | `https://itop.example.com/env-production/combodo-hybridauth/landing.php` (exactly this, no wildcard) |
| | Valid post logout redirect URIs | empty |
| | Web origins | empty (iTop calls Keycloak from the server, not from the browser) |

Why these values:

- **Standard flow only.** hybridauth uses the authorization code flow. Direct access grants would let
  anyone with the client secret exchange a user's password for tokens; implicit flow and service
  accounts are not used.
- **PKCE method empty.** The HybridAuth Keycloak adapter that hybridauth uses does not send PKCE
  parameters, so `S256` or `plain` here would make every login fail. The client is confidential,
  so the code exchange is protected by the client secret.
- **Redirect URI exact.** Keycloak compares redirect URIs case-sensitively. The path comes from the
  folder name `combodo-hybridauth` in iTop's `extensions/` folder, so it must not contain a version
  number.

### Users in Keycloak

hybridauth identifies the user by the **email** that Keycloak returns. So:

- Every user who logs into iTop needs an email address in Keycloak, and it must be the login of
  their iTop user (see [iTop user accounts](#itop-user-accounts)).
- The client needs the `email` client scope. Keycloak assigns it to new clients by default; check
  the **Client scopes** tab of the `itop` client if logins fail with a missing email.
- **Users must not be able to choose their own email.** Whoever can set an email in Keycloak can log
  into iTop as the iTop user with that login. hybridauth 2.1.1 does not check `email_verified`.
  In **Realm settings**:
  - **Login** → **Duplicate emails**: Off (the default).
  - **Login** → **User registration**: Off, unless registration requires email verification.
  - **User profile** → attribute `email` → **Permissions**: only admins can edit it, if your users
    have access to the Keycloak account console. *To be checked in the validation run:* exact field
    names in Keycloak 26.8.

## iTop: log in with Keycloak

Make `config-itop.php` writable as described in
[the prerequisites](itop-prerequisites.md#4-make-the-configuration-file-writable-for-the-edit), then
change two places.

### `allowed_login_types` in `$MySettings`

Add `hybridauth-Keycloak` and keep `form` first:

```php
	'allowed_login_types' => 'form|token|hybridauth-Keycloak',
```

- `Keycloak` is the provider key from the snippet below. Both must be spelled the same,
  case-sensitively.
- `form` stays first: iTop's login page then shows its login form plus a **Sign in with Keycloak**
  button, and local accounts (for example your administrator) can still log in. Combodo's
  documentation states that `form` must remain first for the other login types to be offered.
- `token` stays: the MCP server calls iTop's REST/JSON API with a token.

### `combodo-hybridauth` in `$MyModuleSettings`

```php
	'combodo-hybridauth' => array(
		// Users must already exist in iTop. See "iTop user accounts".
		'synchronize_user' => false,
		'synchronize_contact' => false,
		// Setting "providers" replaces the extension's defaults (Google, Twitter, Facebook, all disabled).
		'providers' => array(
			// The key "Keycloak" selects HybridAuth's Keycloak adapter and is the
			// "hybridauth-Keycloak" in allowed_login_types.
			'Keycloak' => array(
				'enabled' => true,
				// Keycloak base URL: no trailing slash, no "/realms/...".
				// Add "/auth" only if your Keycloak runs with the legacy "/auth" path.
				'url' => 'https://sso.example.com',
				'realm' => 'example',
				'keys' => array(
					'id' => 'itop',
					'secret' => '<client secret from the Credentials tab of the itop client>',
				),
				// Text of the button on iTop's login page.
				'label' => 'Sign in with Keycloak',
			),
		),
	),
```

The Keycloak adapter builds all endpoints from `url` and `realm`:
`https://sso.example.com/realms/example/protocol/openid-connect/auth`, `.../token` and
`.../userinfo`. It asks for the scopes `openid profile email`.

The client secret is stored in `config-itop.php` in plain text. That is one more reason to keep the
file read-only for the web server user only (mode `0440`) and out of backups that many people can
read.

Run `php -l` on the file and make it read-only again, as described in the prerequisites.

## iTop user accounts

### Default: users must exist in iTop

With `synchronize_user => false`, hybridauth creates nothing. When a user comes back from Keycloak,
iTop looks for an **enabled** user of type **External user** whose **login is exactly the email**
Keycloak returned. If there is none, the login is refused with "User not allowed".

For every person who should log in with Keycloak:

1. Make sure a **Person** exists in iTop (usually it does).
2. Create an **External user** (*Admin tools* → *User accounts* → *New* → *External user*) with:
   - **Login**: the user's email exactly as in Keycloak
   - **Contact**: the Person
   - **Profiles**: what this person may do in iTop. To use the assistant, this includes one of the
     profiles from `personal_tokens_allowed_profiles` and `required_profiles` (in the example,
     `Service Desk Agent` or `Support Agent`).
   - **Allowed organizations**: as for any other user
3. If the person already has a **local** user whose login is that email, iTop does not allow a
   second user with the same login. Change the local user's login or delete it, then create the
   External user.

The assistant sees exactly what this iTop user sees. Assign profiles and allowed organizations with
that in mind.

Keep at least one local administrator account. It keeps working with iTop's login form and is your
way in if Keycloak is down or misconfigured.

### Option: create users automatically on first login

hybridauth can create the Person and the External user on a user's first login. Only use this if
every Keycloak user in the realm may have an iTop account.

```php
	'combodo-hybridauth' => array(
		'synchronize_user' => true,
		'synchronize_contact' => true,
		// Organization of new Persons, by name. Must exist in iTop.
		'default_organization' => '<your organization>',
		// Profiles of every new user. Least privilege: Portal user only.
		'default_profiles' => array('Portal user'),
		'providers' => array(
			// ... as above ...
		),
	),
```

> **Warning: `default_profiles` decides what the assistant can see for every new user.** Every user
> created this way gets exactly these profiles, and the assistant acting for them reads everything
> these profiles allow. If you turn on `synchronize_user` and leave `default_profiles` out, the
> extension's built-in default applies: `Portal User` **and `Configuration Manager`**, which gives
> every new Keycloak user read access to the whole CMDB.
>
> Use `Portal user` only. It is not in `personal_tokens_allowed_profiles` or `required_profiles`, so
> new users cannot use the assistant until an administrator gives them an agent profile on purpose.

How the automatic path matches and creates records:

- **Person:** found by email. If none exists, a Person is created in `default_organization` with
  first name, last name and email from Keycloak. With `synchronize_contact => false`, a missing
  Person refuses the login instead.
- **User:** found by login = email. If none exists, an External user with that login is created and
  gets `default_profiles`. Existing users are left unchanged.

Mapping Keycloak groups to iTop profiles (`groups_to_profiles`) is possible but not part of this
example; see Combodo's
[hybridauth documentation](https://www.itophub.io/wiki/page?id=extensions:combodo-hybridauth).

<!-- Ticket 03 inserts here:
     ## Keycloak: client for LibreChat   (field-value table for the confidential client "librechat",
        redirect https://chat.example.com/oauth/openid/callback, same flow settings as "itop")
     ## LibreChat                         (.env OpenID keys, librechat.yaml mcpServers.itop,
        mcpSettings.allowedDomains, modelSpecs, altioo redirect_uris entry for
        https://chat.example.com/api/mcp/itop/oauth/callback) -->

## Check list

Each check builds on the one before; fix a failing check before you go on. Use a private browser
window for the login checks, so that no earlier iTop or Keycloak session gets in the way.

### 1. Keycloak's realm answers

```sh
curl -s https://sso.example.com/realms/example/.well-known/openid-configuration
```

**Expected:** JSON with `"issuer":"https://sso.example.com/realms/example"` and an
`authorization_endpoint` ending in `/protocol/openid-connect/auth`.

**If not:**

| Result | Fix |
|---|---|
| 404 | Wrong realm name, or your Keycloak uses the legacy `/auth` path: then the URL is `https://sso.example.com/auth/realms/example/...`, and `url` in the hybridauth snippet needs `/auth` too. |
| `issuer` with another host or `http://` | Keycloak does not know its public hostname. Set Keycloak's `hostname` option to `https://sso.example.com`. |

### 2. iTop's login page offers Keycloak

Open `https://itop.example.com/` in a private window.

**Expected:** iTop's login form and a **Sign in with Keycloak** button.

**If not:**

| Result | Fix |
|---|---|
| No button | `hybridauth-Keycloak` is missing from `allowed_login_types`, the provider has `'enabled' => false`, or the extension was not ticked in the setup wizard. |
| Error page, and `log/error.log` says "login_mode forced without being configured" or "... properly enabled" | `allowed_login_types` contains `hybridauth-Keycloak` but `providers` has no enabled `Keycloak` entry. The two names must match exactly. |
| PHP error or blank page | Syntax error in `config-itop.php`, or combodo-oauth2-client / itop-attribute-encrypted-password are missing. Check `php -l` and the setup wizard. |

### 3. A Keycloak user logs into iTop

You need a Keycloak user with an email, and an External user in iTop with that email as login.
Click **Sign in with Keycloak** and log in at Keycloak.

**Expected:** Keycloak's login page for realm `example`, then iTop's home page, logged in as that
iTop user.

**If not:**

| Result | Fix |
|---|---|
| Keycloak: "Invalid parameter: redirect_uri" | **Valid redirect URIs** of the `itop` client is not exactly `https://itop.example.com/env-production/combodo-hybridauth/landing.php`. If iTop's `app_root_url` is not the public URL, the callback iTop sends is wrong as well. |
| Keycloak: "Client not found" | `keys` → `id` is not `itop`, or `realm` is wrong. |
| iTop: "User not allowed" | No enabled External user with the Keycloak email as login, or the Keycloak user has no email. |
| iTop shows an error page from `landing.php` right after the Keycloak login | Usually the token request to Keycloak failed: wrong client secret, or iTop cannot reach `https://sso.example.com` from the server (proxy, firewall, TLS trust). |

To see what happens, set `'debug' => true` in the `Keycloak` provider entry and read
`log/hybridauth.log`, and look for the channel `Hybridauth` in `log/error.log`. Remove `debug`
afterwards: the logs then contain the provider configuration including the client secret, and user
profiles.

### 4. The MCP OAuth flow goes through Keycloak to the consent page

Log out of iTop and Keycloak (or use a new private window). Connect an MCP client to
`https://mcp.example.com/mcp`: the client from check 5 of
[the prerequisites](itop-prerequisites.md#5-an-mcp-client-can-connect), or LibreChat once it is set
up.

**Expected:** the client sends you to iTop's login page; you click **Sign in with Keycloak**, log in
at Keycloak, and land on the altioo-oauth-server **consent page** naming the client and
"iTop assistant". After consent, the client is connected.

**If not:**

| Result | Fix |
|---|---|
| After the Keycloak login you land on iTop's home page instead of the consent page | hybridauth returns to the page you came from only if its URL, as PHP sees it (`REQUEST_SCHEME`, `HTTP_HOST`, `REQUEST_URI`), starts with iTop's `app_root_url`. Otherwise it falls back to the home page. Behind a reverse proxy that terminates TLS, PHP often sees `http` or an internal host. Make PHP see the public scheme and host, for example nginx `fastcgi_param REQUEST_SCHEME https;` with the public `Host` header passed through, or Apache `ServerName https://itop.example.com`. *To be checked in the validation run:* these snippets against the reverse proxy used there. Then start the connection in the client again. |
| "Personal tokens not allowed", refusal before the consent page, "Unknown resource" | Not related to Keycloak: see check 5 of [the prerequisites](itop-prerequisites.md#5-an-mcp-client-can-connect). The External user needs the same profiles as a local user would. |

<!-- Ticket 03 adds its checks after this one: LibreChat login via Keycloak; connecting the "itop"
     server opens the iTop consent page; "whoami" in the chat returns the logged-in iTop user. -->
