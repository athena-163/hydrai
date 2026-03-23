---
name: context
description: Inspect whitelisted context trees by structure, semantic search, and exact path reads.
---

Use this skill to work inside a whitelisted context root.

Preferred flow:
1. `context_view` to inspect the tree shape.
2. `context_search` to find relevant areas semantically.
3. `context_read` to inspect exact files or blocks.

Do not guess context paths before you inspect the tree.

## Functions

### `context_view`
When to use:
- first step in a new context root
- when you need folder structure or summaries

Schema:
```json
{
  "id": "string",
  "depth": "integer (optional, default 2)",
  "summary_depth": "integer (optional, default 1)"
}
```

### `context_search`
When to use:
- when you know the concept but not the exact path
- when the context is too large to browse directly

Schema:
```json
{
  "id": "string",
  "query": "string"
}
```

### `context_read`
When to use:
- after `context_view` or `context_search` identifies a specific path
- when you need exact contents rather than summaries

Schema:
```json
{
  "id": "string",
  "path": "string"
}
```

## Example

1. `context_view({"id":"agent"})`
2. `context_search({"id":"agent","query":"memory about deployment"})`
3. `context_read({"id":"agent","path":"memorables/deploy.md"})`
