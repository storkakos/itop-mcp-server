# MCP token info (iTop extension `mcp-token-info`)

A small iTop extension for [itop-mcp-server](../../README.md). It adds one REST/JSON operation,
`mcp/token_info`, that answers for the token it is called with:

- whether the token was issued through [altioo-oauth-server](https://github.com/AltiooBV/altioo-oauth-server)
  OAuth, and for which resource (via altioo's public PHP API `TokenAudience`),
- which iTop user it belongs to.

A personal token a user made by hand under *My Account* answers "not OAuth". It is iTop's counterpart
of dolibarr-restoauth's `restoauth/me` `token` object: the MCP server uses it to accept only tokens
issued through OAuth for its own resource.

## Requirements

| | |
|---|---|
| iTop | 3.2 (tested with 3.2.3-3) |
| authent-token | 2.2.1 or later (part of iTop 3.2) |
| altioo-oauth-server | 0.1.0 or later; optional for the extension, required for an answer "OAuth: yes" |
| REST | `allow_rest_services_via_tokens` and the `token` login type, as altioo already needs |

Without altioo-oauth-server the operation works, says `"oauth_server": false` and reports every
token as not OAuth.

## Install

The same way as the other extensions in [the iTop prerequisites](../../docs/setup/itop-prerequisites.md#install-the-extensions),
in the same wizard run if you install them together:

1. Back up the database and `conf/production/config-itop.php`.
2. Unpack `mcp-token-info-<version>.zip` into iTop's `extensions/` folder, so that
   `extensions/mcp-token-info/module.mcp-token-info.php` exists, readable by the web server user.
3. Make `conf/production/config-itop.php` writable for the web server user (`chmod u+w`).
4. Open `https://<itop>/setup/`, choose **Upgrade an existing iTop instance**, and in the last
   extensions step **tick MCP token info** (`mcp-token-info`); on an upgrade, new extensions are not
   ticked by default. Finish the wizard. It adds no tables and no settings.
5. Make the configuration file read-only again (`chmod 0440`).

Check: `list_operations` now lists `mcp/token_info`:

```sh
curl -s -H "Auth-Token: $TOKEN" --data-urlencode version=1.4 \
  --data-urlencode 'json_data={"operation":"list_operations"}' https://<itop>/webservices/rest.php
```

To remove it, untick it in the setup wizard (upgrade) and delete `extensions/mcp-token-info/`.

## Operation contract: `mcp/token_info`

Request: an ordinary REST/JSON call, in any REST version iTop offers (1.0 to 1.4), authenticated with
the token to ask about. It takes no parameters; any given are ignored.

```sh
curl -s -H "Auth-Token: $TOKEN" --data-urlencode version=1.4 \
  --data-urlencode 'json_data={"operation":"mcp/token_info"}' https://<itop>/webservices/rest.php
```

Answer for a token issued through altioo-oauth-server:

```json
{
  "code": 0,
  "message": "mcp/token_info",
  "extension_version": "0.1.0",
  "oauth_server": true,
  "user": {"id": 7, "login": "lena.local"},
  "token": {
    "class": "PersonalToken",
    "id": 12,
    "oauth": true,
    "resource": {"key": "itop-mcp", "url": "https://mcp.example.com/mcp"},
    "scopes": ["REST/JSON"],
    "expires_at": 1795526400
  }
}
```

| Field | Meaning |
|---|---|
| `code` | `0` on success, as for every REST call |
| `extension_version` | this extension's version |
| `oauth_server` | `true` when altioo-oauth-server's `TokenAudience` API is installed |
| `user.id`, `user.login` | the iTop user the call runs as (the token's owner) |
| `token` | the token of this call; `null` when the call logged in without a token (user and password) |
| `token.class` | `PersonalToken` for personal tokens (OAuth-issued or made by hand), `UserToken` for an application token |
| `token.id` | the token's iTop key |
| `token.oauth` | `true` only when an altioo-oauth-server connection owns the token |
| `token.resource` | `null` unless `oauth`; then `key` is the resource's key in altioo's `resources` setting and `url` the resource URL the token was granted for, spelled as in that setting. `url` is `""` when that resource has since been removed from `resources` |
| `token.scopes` | the token's scopes, e.g. `["REST/JSON"]` |
| `token.expires_at` | the token's expiry as a Unix timestamp, `null` if it has none |

The three token kinds:

| Token | Answer |
|---|---|
| issued through altioo OAuth | `code: 0`, `token.oauth: true`, `token.resource` set |
| made by hand under *My Account* (or by an administrator) | `code: 0`, `token.oauth: false`, `token.resource: null` |
| invalid, expired or revoked | refused by `rest.php` before the operation runs, like any REST call: `{"code": 1, "message": "Error: Invalid login"}` |

A caller accepts a token for a resource only if `code == 0`, `token.oauth == true` and
`token.resource.url` equals its own resource URL exactly.

If the extension is not installed, `rest.php` answers
`{"code": 11, "message": "Error: Unknown verb 'mcp/token_info' in version '1.4'"}`.

## What it does not do

- It answers only for the caller's own token, the one `rest.php` has just logged in with, and only
  if that token belongs to the logged-in user. There is no parameter to ask about another token,
  user or connection, and it never returns a token's secret.
- It does not decide whether a token is accepted; the caller does.
- It needs no rights beyond those of a normal REST call: it reads the token through iTop's own login
  state, not through the user's rights on `PersonalToken`.

## Build the ZIP

```sh
python itop-extension/build.py     # -> itop-extension/dist/mcp-token-info-<version>.zip and its SHA256
```

Python 3.10 or later, standard library only. The ZIP is reproducible: the same sources give the
same bytes on every machine (sorted entries, fixed timestamps and permissions, LF line endings). The
version comes from `extension.xml` and must match `module.mcp-token-info.php`. The ZIP is meant to
be attached to a GitHub release.

## Licence

MIT, see [LICENSE](LICENSE). iTop and altioo-oauth-server are AGPL-3.0; this extension only calls
their APIs and runs inside iTop.
