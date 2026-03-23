---
name: context-write
description: Write managed context content through the control plane when the target context is explicitly whitelisted as writable.
---

Use this skill to create or overwrite content inside a writable context root.

Do not use it for ordinary local files. Use `file-write` for that.
This operation requires the target context id to be whitelisted with `rw` permission.

## Function

### `context_write`
Schema:
```json
{
  "id": "string",
  "path": "string",
  "content": "string"
}
```
