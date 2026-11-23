# The identity-provider path needs combodo-hybridauth's two helper extensions

The setup manuals were planned with two iTop extensions: altioo-oauth-server and combodo-hybridauth. But combodo-hybridauth 2.1.1 cannot run alone. Its module file requires combodo-oauth2-client, which contains the HybridAuth library and its Keycloak adapter. combodo-oauth2-client in turn requires itop-attribute-encrypted-password. So the prerequisites manual lists all three for the identity-provider path, together with their licences: the Combodo Software License for hybridauth, and AGPL-3.0 for both helpers.

Customers download only combodo-hybridauth. iTop 3.2.3 already ships both helpers in `datamodels/2.x/` (combodo-oauth2-client 1.0.9, itop-attribute-encrypted-password 1.1.1, the versions the PoC runs). The manual pins those versions as "ships with iTop 3.2.3" and warns not to copy them into `extensions/`, because the module would then exist twice. This is one reason why iTop 3.2.3 is the minimum when an identity provider is used, while iTop 3.2.1 is still enough without one.

## Considered Options

- **Download and pin all three ZIPs** (ticket 02's first version, with SHA256 values of the GitHub tag archives). Rejected: on iTop 3.2.3 this puts each helper into iTop twice, and it differs from what the PoC tested.
- **Leave the helpers out of the manual.** Rejected: a customer admin would not know why the wizard needs them, or why iTop 3.2.1 and 3.2.2 are not enough for this path.

## Consequences

- An upgrade from iTop 3.2.1 or 3.2.2 that also adds an identity provider must first upgrade iTop to 3.2.3.
- The validation run has to check that the setup wizard installs the hidden helper modules together with hybridauth, because they have no checkbox of their own.
