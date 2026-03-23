---
name: git
description: Work with the local Git repository using controlled shell commands when repository state matters.
---

Use this skill for repository inspection and safe non-interactive Git operations.

Current execution path uses the existing `bash` tool. Keep commands explicit and non-interactive.
Prefer read-only Git inspection unless the task clearly requires a repository mutation.

## Function

### `bash` for Git
Typical commands:
- `git status --short`
- `git diff -- path`
- `git log --oneline -n 10`
- `git show <commit>`

Schema:
```json
{
  "command": "string",
  "timeout": "integer (optional, default 120)"
}
```

Notes:
- avoid interactive Git commands
- do not use destructive commands unless explicitly requested
