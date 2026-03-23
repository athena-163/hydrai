---
name: bash
description: Run shell commands, usually in read-only mode, for deterministic local inspection or controlled execution.
---

Use this skill when a direct shell command is the clearest way to inspect or operate on the local workspace.

Prefer built-in structured tools when they already cover the task.
In read-only mode, only allowlisted commands are permitted.

## Function

### `bash`
Schema:
```json
{
  "command": "string",
  "timeout": "integer (optional, default 120)"
}
```

Notes:
- read-only mode rejects shells, pipes, redirects, and disallowed commands
- protected paths may be blocked by path policy
