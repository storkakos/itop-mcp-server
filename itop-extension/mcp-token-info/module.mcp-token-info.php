<?php
/**
 * @copyright   Copyright (c) 2026 Alexander Stork
 * @license     MIT, see README.md
 */
//
// iTop module definition file
//

// The version below and the one in extension.xml are the same string.
SetupWebPage::AddModule(
	__FILE__,
	'mcp-token-info/0.1.0',
	array(
		// Identification
		//
		'label' => 'MCP token info',
		'category' => 'authentication',

		// Setup
		//
		// authent-token holds the personal tokens this module reports on. altioo-oauth-server is
		// optional: without it, no token counts as OAuth-issued (see main.mcp-token-info.php).
		'dependencies' => array(
			'authent-token/2.2.1',
		),
		'mandatory' => false,
		'visible' => true,

		// Components
		//
		// Included on every page, so rest.php finds the REST service provider among the declared classes.
		'datamodel' => array(
			'main.mcp-token-info.php',
		),
		'webservice' => array(
		),
		'data.struct' => array(
		),
		'data.sample' => array(
		),

		// Documentation
		//
		'doc.manual_setup' => '',
		'doc.more_information' => '',

		// Default settings
		//
		'settings' => array(
		),
	)
);
