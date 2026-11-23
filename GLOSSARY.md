# Glossary

**MCP server**
This product. Receives tool calls from an MCP client and forwards them to iTop with the caller's own token. It stores no user secrets and issues no tokens.
_Avoid_: bridge, proxy

**MCP client**
The application a user chats in that calls the MCP server, e.g. LibreChat.
_Avoid_: frontend, chat

**Authorization server**
The component that issues the access token the MCP client sends to the MCP server. Always iTop with the altioo-oauth-server extension; never the identity provider.
_Avoid_: OAuth server (ambiguous), IdP

**Identity provider**
Where users log in, e.g. Keycloak. It authenticates users for iTop and for the MCP client, but never issues tokens the MCP server accepts.
_Avoid_: SSO, auth server

**iTop prerequisites**
What every customer must set up in iTop before the MCP server works, independent of which identity provider or MCP client they use.

**Example setup**
One documented, non-mandatory way to connect an identity provider and an MCP client (Keycloak and LibreChat) to iTop and the MCP server.
_Avoid_: reference installation
