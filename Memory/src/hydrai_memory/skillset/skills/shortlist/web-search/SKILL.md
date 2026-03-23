---
name: web-search
description: Search the web through the control plane when local context is insufficient.
---

Use this skill when the answer depends on current external information.

Prefer local context and session knowledge first. Use web search when freshness matters.

## Function

### `web_search`
Schema:
```json
{
  "query": "string",
  "count": "integer (optional, default 5)"
}
```

Good uses:
- current events
- current APIs, releases, or pricing
- live service or company facts
