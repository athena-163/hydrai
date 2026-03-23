---
name: attachments
description: Inspect recent session attachments or look up exact attachment tags such as 0001.jpg.
---

Use this skill for session-scoped attachment lookup.

Preferred flow:
1. `latest_attachments` when you need recent tags or summaries.
2. `attachment_info` when you already know exact tags.

## Functions

### `latest_attachments`
Schema:
```json
{
  "session_id": "string",
  "limit": "integer (optional, default 10)"
}
```

### `attachment_info`
Schema:
```json
{
  "session_id": "string",
  "tags": ["string"]
}
```

Typical tags look like `0001.jpg` or `0003.mp4`.
