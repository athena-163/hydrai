---
name: web-fetch
description: Fetch the content of one URL when you already know the target page.
---

Use this skill when you already have a specific URL and need its contents.

Prefer `web_search` first when you do not yet know the right page.

## Function

### `web_fetch`
Schema:
```json
{
  "url": "string"
}
```

Notes:
- private or loopback hosts are blocked
- HTML is stripped to readable text
