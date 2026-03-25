# Hydrai Toolbox Specification

## 1. Purpose

`Toolbox` is the system-space internal service that bridges Hydrai callers to
credentialed external tools.

It should:

1. hide provider-specific auth and protocol details
2. keep all keys, tokens, and mailbox credentials in system space
3. expose normalized internal APIs to trusted Hydrai callers
4. enforce mailbox-level access policy for email tools

`Toolbox` is not a general workflow engine. It is a narrow bridge layer.

## 2. Service Shape

`Toolbox` should be:

1. a standalone installable Python package
2. a local HTTP service
3. config-driven
4. stateless at the request layer

Like `Intelligence` and `Memory`, it should have:

1. one control/help port
2. a set of internal tool endpoints

Recommended band:

1. `60000`: control/help
2. `60100+`: tool endpoints if later split by port

For v1, one control/help port plus one HTTP service process is sufficient.

## 3. Trust Model

`Toolbox` follows Hydrai internal auth rules from [TRUST.md](/Users/zeus/Codebase/hydrai/TRUST.md).

High-level trust assumptions:

1. `Toolbox` runs in system space
2. sandbox callers must not have direct access to provider credentials
3. `Brain -> Toolbox` is authenticated internal traffic
4. in `dev` mode, auth may be bypassed explicitly
5. in `secure` mode, `Toolbox` requires internal Hydrai tokens

`Toolbox` should treat caller identity as part of authorization for email.

## 4. Caller Identity Model

For mailbox-gated APIs, `Toolbox` should receive and evaluate:

1. `sandbox_id`
2. `identity_id`

This is required because one mailbox may be shared with:

1. multiple identities
2. identities from different sandboxes

So access control must not be mailbox-only or sandbox-only. It must be:

1. mailbox address
2. caller sandbox
3. caller identity
4. requested operation

## 5. Config Schema

Directionally, `Toolbox.json` should look like:

```json
{
  "control_port": 60000,
  "web_search": {
    "provider": "brave",
    "brave": {
      "key_env": "BRAVE_API_KEY",
      "timeout_sec": 15
    }
  },
  "email": {
    "mailboxes": [
      {
        "address": "athena@example.com",
        "backend": "himalaya",
        "backend_ref": "athena",
        "display_name": "Athena Mail",
        "grants": [
          {
            "sandbox_id": "olympus",
            "identity_id": "athena",
            "mode": "rw"
          },
          {
            "sandbox_id": "olympus",
            "identity_id": "zeus",
            "mode": "ro"
          },
          {
            "sandbox_id": "apollo",
            "identity_id": "athena",
            "mode": "ro"
          }
        ]
      }
    ],
    "backends": {
      "himalaya": {
        "bin_name": "himalaya",
        "timeout_sec": 60
      }
    }
  }
}
```

### 5.1 Top-Level Fields

1. `control_port`: service help/control port
2. `web_search`: normalized web-search backend config
3. `email`: mailbox registry and backend config

### 5.2 Web Search Config

Required fields:

1. `provider`

Provider-specific config should live under provider-named sections.

Initial v1 provider:

1. `brave`

Recommended fields for `brave`:

1. `key_env`
2. `timeout_sec`

### 5.3 Email Mailbox Registry

Each mailbox entry should define:

1. `address`: canonical mailbox email address
2. `backend`: backend type, for example `himalaya`
3. `backend_ref`: backend-local account reference if needed
4. `display_name`
5. `grants`: explicit access grants

Mailbox address should be unique across the config.

### 5.4 Email Grants

Each grant should define:

1. `sandbox_id`
2. `identity_id`
3. `mode`

`mode`:

1. `ro`
2. `rw`

Rules:

1. one mailbox may grant access to many identities
2. those identities may come from different sandboxes
3. `ro` allows read-style operations only
4. `rw` allows both read-style and write-style operations

### 5.5 Email Backend Config

`email.backends` should hold backend-type configuration shared by mailbox
entries.

Initial v1 backend types:

1. `himalaya`
2. `imap_smtp`

Future backend types may include:

1. `m365_graph`

Caller APIs must not change when backend type changes.

`imap_smtp` should support direct IMAP and SMTP settings plus optional IMAP
`ID` fields for providers such as NetEase `163.com` that require RFC2971-style
client identification before `SELECT`.

`gmail_oauth` should support Gmail-specific OAuth 2.0 and use the Gmail API
for search, read, send, and draft operations.

## 6. Control Port Endpoints

`GET /health`

Returns:

```json
{
  "status": "ok",
  "service": "toolbox",
  "port": 60000
}
```

`GET /help`

Should return:

1. service name
2. security mode
3. config path
4. configured web-search provider
5. configured mailbox addresses
6. endpoint inventory

Example shape:

```json
{
  "service": "Hydrai Toolbox",
  "security_mode": "dev",
  "config_path": "/Users/zeus/Public/hydrai/Toolbox.json",
  "control_port": 60000,
  "web_search_provider": "brave",
  "mailboxes": [
    {
      "address": "athena@example.com",
      "backend": "himalaya"
    }
  ],
  "endpoints": {
    "health": "GET /health",
    "help": "GET /help",
    "web_search": "POST /web/search",
    "email_search": "POST /email/search",
    "email_read": "POST /email/read",
    "email_send": "POST /email/send",
    "email_draft": "POST /email/draft"
  }
}
```

## 7. Web Search API

### `POST /web/search`

Purpose:

1. perform normalized web search

Request:

```json
{
  "query": "latest OpenAI API pricing",
  "count": 5
}
```

Response:

```json
{
  "results": [
    {
      "title": "Result title",
      "url": "https://example.com/page",
      "description": "Short result description"
    }
  ]
}
```

Rules:

1. callers do not choose provider
2. provider is selected by config
3. provider key comes from env var

## 8. Email Authorization Model

Before any email operation, `Toolbox` should:

1. resolve the mailbox by `address`
2. resolve the caller by `sandbox_id + identity_id`
3. find a matching grant
4. verify the operation is allowed under that grant's mode

Operation classes:

1. read class:
   - search
   - read
2. write class:
   - send
   - draft

Authorization rules:

1. `ro` may call read class only
2. `rw` may call read class and write class
3. missing grant means deny

## 9. Email APIs

Caller should only need to know:

1. mailbox address
2. normalized operation parameters

Caller should not know:

1. backend type
2. backend account id
3. provider protocol details
4. OAuth or password details

### 9.1 `POST /email/search`

Request:

```json
{
  "sandbox_id": "olympus",
  "identity_id": "athena",
  "address": "athena@example.com",
  "query": "from:zeus subject:deploy",
  "limit": 10,
  "folder": "INBOX"
}
```

Response:

```json
{
  "messages": [
    {
      "id": "123",
      "subject": "Deploy notes",
      "from": "zeus@example.com",
      "date": "2026-01-01T12:00:00Z"
    }
  ]
}
```

### 9.2 `POST /email/read`

Request:

```json
{
  "sandbox_id": "olympus",
  "identity_id": "athena",
  "address": "athena@example.com",
  "message_id": "123"
}
```

Response:

```json
{
  "id": "123",
  "body": "full message body"
}
```

### 9.3 `POST /email/send`

Request:

```json
{
  "sandbox_id": "olympus",
  "identity_id": "athena",
  "address": "athena@example.com",
  "to": ["zeus@example.com"],
  "cc": [],
  "bcc": [],
  "subject": "Deploy update",
  "body": "Here is the update."
}
```

Response:

```json
{
  "ok": true
}
```

### 9.4 `POST /email/draft`

Request:

```json
{
  "sandbox_id": "olympus",
  "identity_id": "athena",
  "address": "athena@example.com",
  "to": ["zeus@example.com"],
  "cc": [],
  "bcc": [],
  "subject": "Draft subject",
  "body": "Draft body"
}
```

Response:

```json
{
  "ok": true,
  "draft_id": "uuid-or-provider-id"
}
```

## 10. Email Backend Contract

Backends should implement an internal normalized interface roughly like:

1. `search(query, limit, account="", folder="") -> dict`
2. `read(message_id, account="") -> dict`
3. `send(to, subject, body, account="", cc=None, bcc=None) -> dict`
4. `draft(to, subject, body, account="", cc=None, bcc=None) -> dict`

Mailbox registry maps:

1. caller-facing `address`
2. internal `backend`
3. internal `backend_ref`

So the caller always passes address, and `Toolbox` resolves backend details.

## 11. Initial Backend Choices

### 11.1 Web Search

Initial v1:

1. `brave`

This matches AIOS and is sufficient for a first Hydrai pass.

### 11.2 Email

Initial v1:

1. `himalaya`

Rationale:

1. AIOS already proved it
2. it keeps mailbox protocol handling on the host
3. it can already work with multiple host-configured accounts
4. it is a good bridge for Gmail and other modern providers when the host tool
   supports OAuth2

## 12. Gmail and Other Modern Mail Systems

Hydrai should explicitly support the idea that different mail systems require
different auth/backends.

For Gmail/Workspace:

1. prefer host tooling or backends that support OAuth2 / XOAUTH2
2. do not design around deprecated password-only login assumptions

This strengthens the case for backend abstraction inside `Toolbox`.

## 13. Errors

Normalized errors should return:

1. HTTP `400` for bad request
2. HTTP `401` for missing/invalid internal auth
3. HTTP `403` for mailbox access denied
4. HTTP `404` for unknown mailbox address
5. HTTP `500` or `502` for backend/provider failures

JSON shape:

```json
{
  "error": "human readable message"
}
```

## 14. Concurrency

Preferred rule:

1. maximize parallelism where safe
2. backend-specific serialization may exist if a provider tool requires it

At high level:

1. web search can be parallel
2. email search/read can usually be parallel
3. email send/draft may stay conservative if the backend tool is not clearly
   safe for concurrent mutation

If backend behavior is unclear, default to:

1. parallel across sandboxes
2. conservative serialization per mailbox backend ref

## 15. What Toolbox Should Not Do

`Toolbox` should not:

1. store mailbox credentials in sandbox space
2. expose provider-specific auth or URLs to callers
3. own durable mailbox state
4. own identity-level policy beyond configured mailbox grants
5. embed search/mail logic into `Brain`

## 16. V1 Implementation Direction

The first implementation should likely include:

1. config loader and validator
2. internal auth gate
3. control/help server
4. Brave web-search provider
5. Himalaya email provider
6. mailbox registry and grant enforcement
7. tests for:
   - config validation
   - mailbox authorization
   - provider dispatch
   - live Brave path if key exists
   - live Himalaya path if configured on the host
