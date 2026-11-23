"""TEST ONLY. The config-itop.php edits of the two manuals, applied as an admin would type them."""
import re

from common import KC_SECRET_ITOP

# docs/setup/itop-prerequisites.md, "Settings in $MyModuleSettings"
PREREQ_BLOCK = """
	'authent-token' => array(
		// Only the profiles that should use the assistant. No Administrator (see above).
		'personal_tokens_allowed_profiles' => array('Service Desk Agent', 'Support Agent'),
		// Shows "Personal Tokens" under My Account, where users see and end their connections.
		'enable_myaccount_menu' => true,
	),

	'altioo-oauth-server' => array(
		// The MCP client's callback, exactly as the client sends it.
		'redirect_uris' => array(
			'https://chat.example.com/api/mcp/itop/oauth/callback',
		),
		// Callbacks on localhost/127.0.0.1 are for local tests only. Keep false in production.
		'allow_loopback' => false,

		'access_token_lifetime' => 3600, // seconds
		'grant_idle_days' => 30,
		'max_grant_days' => 90,

		'resources' => array(
			'itop-mcp' => array(
				'url' => 'https://mcp.example.com/mcp',
				'label' => 'iTop assistant',
				'scope_prefix' => 'REST/JSON',
				'default_scopes' => array('REST/JSON'),
				'bearer_methods' => array('header'),
				'required_profiles' => array('Service Desk Agent', 'Support Agent'),
			),
		),
	),

"""

# docs/setup/example-keycloak-librechat.md, "combodo-hybridauth in $MyModuleSettings"
HYBRIDAUTH_BLOCK = """	'combodo-hybridauth' => array(
		// Users must already exist in iTop. See "iTop user accounts".
		'synchronize_user' => false,
		'synchronize_contact' => false,
		// Setting "providers" replaces the extension's defaults (Google, Twitter, Facebook, all disabled).
		'providers' => array(
			'Keycloak' => array(
				'enabled' => true,
				'url' => 'https://sso.example.com',
				'realm' => 'example',
				'keys' => array(
					'id' => 'itop',
					'secret' => '%s', // test value
				),
				'label' => 'Sign in with Keycloak',
			),
		),
	),
""" % KC_SECRET_ITOP


def _login_types(s: str, add: str) -> str:
    line = re.search(r"\t'allowed_login_types' => '([^']*)',\n", s)
    types = line.group(1).split("|")
    assert types[0] == "form", types
    if add not in types:
        types.append(add)
    return s.replace(line.group(0), f"\t'allowed_login_types' => '{'|'.join(types)}',\n", 1)


def apply_prerequisites(s: str) -> str:
    if "'altioo-oauth-server' =>" in s:
        return s
    s = _login_types(s, "token")
    line = re.search(r"\t'allowed_login_types' => '[^']*',\n", s).group(0)
    s = s.replace(line, line + "\n\t'allow_rest_services_via_tokens' => true,\n", 1)
    return s.replace("$MyModuleSettings = array(\n", "$MyModuleSettings = array(\n" + PREREQ_BLOCK, 1)


def apply_hybridauth(s: str) -> str:
    if "'Keycloak' => array(" in s:
        return s
    s = _login_types(s, "hybridauth-Keycloak")
    # Replace the block the setup wizard wrote with the manual's block.
    m = re.search(r"\t'combodo-hybridauth' => array \(\n.*?\n\t\),\n", s, flags=re.S)
    assert m, "the setup wizard's combodo-hybridauth block was not found"
    return s[:m.start()] + HYBRIDAUTH_BLOCK + s[m.end():]
