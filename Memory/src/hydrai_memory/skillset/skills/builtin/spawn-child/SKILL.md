---
name: spawn-child
description: Delegate a scoped subtask to an explicit worker when more cognition or a different worker is needed.
---

Use this skill when the current node should create a child task.

Do not use it for trivial work that can be finished directly.
Choose a concrete `worker_id`; Brain will reject unknown workers.

## Function

### `spawn_child`
Schema:
```json
{
  "worker_id": "string",
  "task": "string",
  "context": ["string"],
  "contexts": ["string"],
  "files": ["string"],
  "websites": ["string"],
  "insights": ["string"],
  "required_fields": ["string"]
}
```

Required fields:
- `worker_id`
- `task`
