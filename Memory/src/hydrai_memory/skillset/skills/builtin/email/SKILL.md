---
name: email
description: Search, read, draft, and send email through the control plane.
---

Use this skill for structured email operations.

Preferred flow:
1. `email_search` to find messages.
2. `email_read` to inspect one message.
3. `email_draft` or `email_send` once the content is ready.

## Functions

### `email_search`
Schema:
```json
{
  "query": "string",
  "limit": "integer (optional, default 10)",
  "account": "string (optional)",
  "folder": "string (optional)"
}
```

### `email_read`
Schema:
```json
{
  "message_id": "string",
  "account": "string (optional)"
}
```

### `email_draft`
Schema:
```json
{
  "to": ["string"],
  "subject": "string",
  "body": "string",
  "account": "string (optional)",
  "cc": ["string"],
  "bcc": ["string"]
}
```

### `email_send`
Schema:
```json
{
  "to": ["string"],
  "subject": "string",
  "body": "string",
  "account": "string (optional)",
  "cc": ["string"],
  "bcc": ["string"]
}
```
