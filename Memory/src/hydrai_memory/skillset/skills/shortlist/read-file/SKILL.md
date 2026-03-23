---
name: read-file
description: Read a local file by absolute path when a context root is not the right abstraction.
---

Use this skill for direct file reads by absolute path.

Prefer the `context` skill when the file belongs to a managed context tree.
Use `read_file` when you already have the exact filesystem path.

## Function

### `read_file`
Schema:
```json
{
  "path": "string"
}
```

Notes:
- path must be absolute
- protected roots may be blocked by Brain path policy
