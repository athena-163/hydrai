---
name: file-write
description: Create or edit local UTF-8 text files by absolute path.
---

Use this skill for direct filesystem text edits when Brain has permission to touch the path.

Prefer precise edits over broad rewrites.

## Functions

### `write_file`
Schema:
```json
{
  "path": "string",
  "content": "string"
}
```

### `edit_file`
Schema:
```json
{
  "path": "string",
  "old": "string",
  "new": "string"
}
```

Notes:
- both functions require absolute paths
- path policy may block protected roots
