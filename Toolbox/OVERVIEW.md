# Hydrai Toolbox

`Toolbox` is Hydrai's system-space bridge to external tools, especially tools
that require credentials, API keys, host-local configuration, or privileged
network access.

It is the tool-side sibling of `Intelligence`:

- `Intelligence` wraps AI models
- `Toolbox` wraps external non-model tools

## Role

`Toolbox` should be:

1. a standalone installable Python package
2. a stateless service at the request layer
3. config-driven
4. internal-only, protected by Hydrai trust/auth

Like `Intelligence`, it should keep credentials in environment variables or
host-local tool config, not in sandbox space.

## Scope

Initial v1 tools:

1. web search
2. email

Future examples:

1. calendar
2. contacts
3. cloud storage
4. issue trackers
5. messaging integrations

## Placement

`Toolbox` runs in system space.

Sandbox callers never talk to providers directly.

The intended trust path is:

1. `Brain -> Toolbox`
2. `Toolbox -> external provider or local host tool`

This keeps all provider credentials, mail config, API keys, and provider quirks
out of sandbox space.

## Port Band

Recommended band:

1. `60000`: control/help
2. `60100+`: tool-facing public internal endpoints

Exact ports should come from config, not code.

## Web Search

AIOS already proved one useful baseline:

1. Brave Search API

Hydrai should keep the provider behind config. The caller should ask for
`web_search`; whether that is implemented by Brave or another provider is a
system-space deployment choice.

High-level rules:

1. provider selection comes from config
2. API key comes from env var
3. callers do not know provider-specific auth or URLs
4. result format should be normalized across providers

## Email

AIOS currently used:

1. `HimalayaEmailProvider`
2. backed by the host-local `himalaya` CLI

That is still a useful baseline because it keeps protocol complexity outside
Hydrai and lets the host own actual mailbox account setup.

### Email Access Control

Unlike web search, email access needs mailbox-level gating.

`Toolbox` should have config that defines:

1. mailbox/account id
2. display email address
3. backend/provider type
4. which sandboxs and identities may access it
5. whether each access path is `ro` or `rw`

That means mailbox/account id should appear explicitly in API parameters, and
`Toolbox` should reject calls that are not authorized for the requesting
sandbox/identity.

High-level access rule:

1. `ro` can search/read
2. `rw` can search/read/send/draft

## Gmail and Modern Provider Support

Hydrai should not assume all email is simple username/password IMAP/SMTP.

Current official Gmail position:

1. Gmail supports standard IMAP, POP, and SMTP
2. modern auth is OAuth 2.0 / SASL XOAUTH2
3. password-only "less secure app" style access should be treated as obsolete
4. app-password flows may still exist in some cases, but should not be the
   primary architecture target

Sources:

1. [Google Gmail IMAP/SMTP docs](https://developers.google.com/gmail/imap/imap-smtp)
2. [Google Gmail XOAUTH2 docs](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol)
3. [Google Workspace admin guidance](https://support.google.com/a/answer/9003945?hl=en-na)

So for Hydrai v1, the most practical email provider shapes are:

1. host-local CLI/provider bridge such as `himalaya`
2. traditional IMAP/SMTP accounts already configured on the host
3. Gmail/Workspace accounts via host tools that support OAuth2

This suggests a clean design direction:

1. `Toolbox` should support multiple email backends
2. backend choice is per mailbox/account in config
3. the API seen by `Brain` stays normalized

## Service Shape

At high level, `Toolbox` should expose:

1. control/help endpoint
2. web search endpoint
3. email search endpoint
4. email read endpoint
5. email send endpoint
6. email draft endpoint

It should also expose enough help metadata so other Hydrai services do not
need to inspect code to discover available tools and mailbox ids.

## Design Principles

1. no provider secrets in sandbox space
2. config chooses providers; callers use normalized APIs
3. mailbox access is explicitly gated by sandbox and identity
4. service remains narrow and stateless at the request layer
5. tool-specific state should stay in the external provider or host tool, not
   in `Toolbox`

## Next Step

The next document should be `Toolbox/SPEC.md`, covering:

1. config schema
2. auth/trust behavior
3. normalized web search API
4. normalized email APIs
5. mailbox permission model
6. supported email backend types
