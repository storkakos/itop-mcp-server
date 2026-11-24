<?php
/**
 * @copyright   Copyright (c) 2026 Alexander Stork
 * @license     MIT, see README.md
 */

use Combodo\iTop\Application\Helper\Session;

/**
 * The answer of mcp/token_info. rest.php sends its public properties as JSON.
 */
class McpTokenInfoResult extends RestResult
{
	/** @var string this extension's version */
	public $extension_version;
	/** @var bool whether altioo-oauth-server's TokenAudience API is installed */
	public $oauth_server;
	/** @var array{id: int, login: string} the user the call is made as */
	public $user;
	/** @var array<string, mixed>|null the token the call is made with; null for a login without a token */
	public $token;
}

/**
 * REST/JSON operation mcp/token_info: tells the caller about the token it calls with.
 *
 * It answers only for the caller's own token, the one rest.php has just logged in with, and takes no
 * parameters, so it cannot be pointed at another user's token or connection. A call with an invalid
 * token never gets here: rest.php refuses it as for any operation.
 */
class McpTokenInfoRestService implements iRestServiceProvider
{
	public const VERSION = '0.1.0';
	public const VERB = 'mcp/token_info';

	private const TOKEN_LOGIN_MODES = array('token', 'rest-token');
	private const TOKEN_AUDIENCE = 'Altioo\\iTop\\Extension\\OAuthServer\\TokenAudience';
	private const TOKEN_INTERFACE = 'Combodo\\iTop\\AuthentToken\\Model\\iToken';

	public function ListOperations($sVersion)
	{
		// Same answer in every REST version: the operation does not depend on it.
		return array(
			array(
				'verb' => self::VERB,
				'description' => 'Whether the token of this call was issued through OAuth, for which resource, and its user',
			),
		);
	}

	public function ExecOperation($sVersion, $sVerb, $aParams)
	{
		if ($sVerb !== self::VERB) {
			$oResult = new RestResult();
			$oResult->code = RestResult::UNKNOWN_OPERATION;
			$oResult->message = "Unknown verb '$sVerb'";
			return $oResult;
		}

		$oResult = new McpTokenInfoResult();
		$oResult->extension_version = self::VERSION;
		$oResult->oauth_server = class_exists(self::TOKEN_AUDIENCE);
		$iUserId = (int) UserRights::GetUserId();
		$oResult->user = array('id' => $iUserId, 'login' => (string) UserRights::GetUser());
		$oResult->token = $this->CallerToken($iUserId);
		$oResult->message = self::VERB;

		return $oResult;
	}

	/**
	 * The token rest.php logged this call in with, or null when it logged in without one.
	 *
	 * @return array<string, mixed>|null
	 */
	private function CallerToken(int $iUserId): ?array
	{
		// rest.php resets the session before its login, so these are this call's own values,
		// set by authent-token's TokenLoginExtension when it accepted the token.
		if (!in_array(Session::Get('login_mode'), self::TOKEN_LOGIN_MODES, true)) {
			return null;
		}
		$sClass = (string) Session::Get('token_class');
		$iId = (int) Session::Get('token_id');
		if ($iId <= 0 || !class_exists($sClass) || !is_subclass_of($sClass, self::TOKEN_INTERFACE)) {
			return null;
		}
		$oToken = MetaModel::GetObject($sClass, $iId, false, true);
		// Never answer for a token of another user.
		if ($oToken === null || (int) $oToken->GetUser()->GetKey() !== $iUserId) {
			return null;
		}

		$aToken = array(
			'class' => $sClass,
			'id' => $iId,
			'oauth' => false,
			'resource' => null,
			'scopes' => $this->Scopes($oToken),
			'expires_at' => $this->ExpiresAt($oToken),
		);

		if ($oToken instanceof PersonalToken && class_exists(self::TOKEN_AUDIENCE)) {
			$sAudience = self::TOKEN_AUDIENCE;
			// null: no OAuth connection owns this token (made by hand under My Account, or by an administrator).
			$oAudience = $sAudience::Of($iId);
			if ($oAudience !== null) {
				$aToken['oauth'] = true;
				$aToken['resource'] = array(
					'key' => $oAudience->sResourceKey,
					// Empty when that resource is no longer configured.
					'url' => $oAudience->sResourceUrl,
				);
			}
		}

		return $aToken;
	}

	/**
	 * @return string[]
	 */
	private function Scopes(DBObject $oToken): array
	{
		if (!MetaModel::IsValidAttCode(get_class($oToken), 'scope')) {
			return array();
		}
		$oScope = $oToken->Get('scope');

		return $oScope instanceof ormSet ? array_values(array_map('strval', $oScope->GetValues())) : array();
	}

	private function ExpiresAt(DBObject $oToken): ?int
	{
		if (!MetaModel::IsValidAttCode(get_class($oToken), 'expiration_date')) {
			return null;
		}
		$sDate = $oToken->Get('expiration_date');
		if ($sDate === null || $sDate === '') {
			return null;
		}

		// Stored as 'Y-m-d H:i:s' in iTop's time zone, the PHP default time zone iTop sets.
		return (new DateTime((string) $sDate))->getTimestamp();
	}
}
