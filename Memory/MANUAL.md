# Hydrai Memory Brain API Manual

This manual describes the sandbox-facing `Memory` tool APIs that `Brain`
calls on the sandbox port, for example `http://127.0.0.1:62001`.

All requests are JSON `POST` unless otherwise noted.

## Discovery

- `GET /help`
  Returns the sandbox route inventory, current sandbox id, context config path,
  watchdog status, and `manual_path`.

- `GET /health`
  Returns simple liveness status.

## Target Model

Generic tree APIs use:

- `target_type`
  One of:
  - `resource`
  - `identity`
  - `session`
  - `human`
  - `native`
- `target_id`
  The sandbox-local id of that target.

`resource` targets must already be registered in `Memory`.

## 1. Generic Tree APIs

These APIs expose structured file access over managed trees. They are the
generic substrate behind resources, identities, sessions, humans, and native
participants.

### `POST /tree/view`

Purpose:
- inspect a tree structure with summaries

Request:

```json
{
  "target_type": "resource",
  "target_id": "workspace-main",
  "path": "",
  "depth": 2,
  "summary_depth": 1
}
```

Response:
- structured tree view from `ContexTree.view(...)`

### `POST /tree/read`

Purpose:
- read exact file paths

Request:

```json
{
  "target_type": "resource",
  "target_id": "workspace-main",
  "paths": ["notes.md", "docs/plan.md"]
}
```

Response:

```json
{
  "notes.md": "file content",
  "docs/plan.md": "file content"
}
```

### `POST /tree/search`

Purpose:
- semantic search inside one target tree

Request:

```json
{
  "target_type": "resource",
  "target_id": "workspace-main",
  "query_text": "API architecture and machine learning project",
  "top_k": 5,
  "min_score": 0.3,
  "paths": ["docs", "notes"]
}
```

Notes:
- `query_text` is the normal caller path.
- `query_embed` also exists but should usually stay internal.
- omit `paths` to search the whole tree.

Response:

```json
{
  "results": [
    {
      "path": "docs/api_design.txt",
      "summary": "Matched summary text",
      "score": 0.82
    }
  ],
  "checked": 12,
  "missing": 0
}
```

### `POST /tree/write`

Purpose:
- overwrite one text file

Request:

```json
{
  "target_type": "resource",
  "target_id": "workspace-main",
  "path": "notes.md",
  "content": "new content",
  "summary": "optional caller summary"
}
```

Response:

```json
{
  "ok": true
}
```

### `POST /tree/append`

Purpose:
- append text to one file

Request:

```json
{
  "target_type": "session",
  "target_id": "athena-artemis",
  "path": "draft.md",
  "content": "\nmore lines",
  "summary": ""
}
```

Response:

```json
{
  "ok": true
}
```

### `POST /tree/delete`

Purpose:
- delete one file or subtree path

Request:

```json
{
  "target_type": "resource",
  "target_id": "workspace-main",
  "path": "old-notes.md"
}
```

Response:

```json
{
  "ok": true
}
```

## 2. Brain Bootstrap

### `POST /brain/bootstrap`

Purpose:
- assemble the deterministic root bootstrap package for one Brain request

Notes:
- this replaces `identity/profile` as the normal root-entry API
- `session_id` may be omitted for monologue or evolve-style requests
- search is only run when `query` is non-empty

Request:

```json
{
  "identity_id": "athena",
  "requestor_id": "zeus",
  "session_id": "chat-1",
  "query": "summarize the latest design status",
  "top_k": 10,
  "min_score": 0.3,
  "attachment_limit": 5
}
```

Response:

```json
{
  "target_identity_id": "athena",
  "requestor_id": "zeus",
  "requestor_persona": "Project owner",
  "target_profile": {
    "persona": "Strategist",
    "soul": "Core self",
    "self_dynamic": "",
    "friends": [],
    "sessions": [
      {
        "id": "chat-1",
        "summary": ""
      }
    ]
  },
  "friend_ids": [],
  "session_ids": ["chat-1"],
  "session": {
    "id": "chat-1",
    "context": "",
    "summary": "",
    "participants": {
      "athena": "rw",
      "zeus": "ro"
    },
    "resources": {
      "workspace-main": "rw"
    },
    "mounted_resources": [
      {
        "id": "workspace-main",
        "type": "context_tree",
        "summary": ""
      }
    ],
    "latest_attachments": [
      {
        "tag": "0001.jpg",
        "path": "attachments/0001.jpg",
        "summary": "diagram image"
      }
    ],
    "search": {
      "results": []
    }
  },
  "skill_shortlist": [
    {
      "name": "context",
      "category": "shortlist",
      "path": "shortlist/context/SKILL.md",
      "summary": "Resource reading and search skill",
      "prompt_text": "# Context ..."
    }
  ]
}
```

## 3. Identity APIs

These are compact identity-specific tools built on top of `IdentityState`.

### `POST /identity/relations`

Purpose:
- fetch persona + relationship file content for a subset of related ids

Notes:
- target ids may be normal identities, humans, or native participants
- missing ids are ignored

Request:

```json
{
  "identity_id": "athena",
  "friend_ids": ["artemis", "zeus", "codex"]
}
```

Response:

```json
{
  "persona_map": {
    "artemis": "Persona text",
    "zeus": "Persona text"
  },
  "dynamic_map": {
    "artemis": "dynamic markdown content"
  }
}
```

### `POST /identity/sessions`

Purpose:
- fetch ongoing continuity files for a subset of sessions

Request:

```json
{
  "identity_id": "athena",
  "session_ids": ["athena-artemis", "athena-zeus"]
}
```

Response:

```json
{
  "ongoing_map": {
    "athena-artemis": "ongoing markdown content"
  }
}
```

### `POST /identity/memorables-search`

Purpose:
- semantic search inside `memorables/`, using plain text query from the caller

Behavior:
- `Memory` creates the embedding internally
- best matches return full file contents
- trailing matches return summaries only

Request:

```json
{
  "identity_id": "athena",
  "query": "planning lessons from the Artemis project",
  "top_content_n": 3,
  "top_summary_k": 5,
  "min_score": 0.3
}
```

Response:

```json
{
  "best_contents": [
    {
      "name": "0001.first-project.md",
      "score": 0.88,
      "content": "full memorable content"
    }
  ],
  "more_summaries": [
    {
      "name": "0004.architecture-note.md",
      "score": 0.61,
      "summary": "short memorable summary"
    }
  ]
}
```

## 4. Session APIs

These are compact session tools built on top of `SessionBook`.

### `POST /session/recent`

Purpose:
- fetch recent session package
- optionally augment it with query-driven semantic hits

Request:

```json
{
  "session_id": "athena-artemis",
  "query": "recent discussion about deployment",
  "top_k": 8,
  "min_score": 0.3
}
```

If `query` is omitted or empty, this becomes the plain recent-context call.

Response:

```json
{
  "context": "recent assembled context",
  "summary": "session summary",
  "identities": {
    "athena": "rw",
    "artemis": "ro"
  },
  "resources": {
    "workspace-main": "rw"
  },
  "results": [
    {
      "path": "000003.log",
      "summary": "matched chapter summary",
      "score": 0.72
    }
  ]
}
```

### `POST /session/search`

Purpose:
- comprehensive semantic search by plain text across:
  - session chapters
  - session attachment summaries
  - all mounted resources

Behavior:
- `Memory` embeds the query internally
- session-root matches keep normal relative paths such as `attachments/0003.jpg`
- resource matches are annotated with origin metadata
- all per-root results are merged and re-sorted globally

Request:

```json
{
  "session_id": "athena-artemis",
  "query": "diagram about API architecture",
  "top_k": 10,
  "min_score": 0.3
}
```

Response:

```json
{
  "results": [
    {
      "source_type": "session",
      "source_id": "athena-artemis",
      "path": "attachments/0003.jpg",
      "summary": "diagram summary",
      "score": 0.85
    },
    {
      "source_type": "resource",
      "source_id": "workspace-main",
      "path": "docs/api_design.txt",
      "summary": "API design summary",
      "score": 0.79
    }
  ]
}
```

### `POST /session/latest-attachments`

Purpose:
- retrieve the most recent attachment summaries with full file paths

Request:

```json
{
  "session_id": "athena-artemis",
  "limit": 10
}
```

Response:

```json
[
  {
    "tag": "0003.jpg",
    "path": "/abs/path/to/session/attachments/0003.jpg",
    "summary": "attachment summary"
  }
]
```

## 5. Skill APIs

These are discovery/install tools over sandbox-visible skills.

Visible categories:
- `shortlist`
- `builtin`
- optional `user`

Visibility is filtered by the normal identity's coarse skill allow/deny config.

### `POST /skills/list`

Purpose:
- list all visible skills for one normal identity

Request:

```json
{
  "identity_id": "athena"
}
```

Response:

```json
{
  "results": [
    {
      "name": "context",
      "path": "/Users/zeus/Public/hydrai/skills/shortlist/context",
      "summary": "Inspect whitelisted context trees by structure, semantic search, and exact path reads.",
      "category": "shortlist"
    }
  ]
}
```

### `POST /skills/search`

Purpose:
- semantic search over visible skills

Request:

```json
{
  "identity_id": "athena",
  "query": "read a file from local disk",
  "limit": 5,
  "min_score": 0.3
}
```

Response:

```json
{
  "results": [
    {
      "name": "read-file",
      "category": "shortlist",
      "path": "/Users/zeus/Public/hydrai/skills/shortlist/read-file",
      "summary": "Read a local file by absolute path when a context root is not the right abstraction.",
      "score": 0.84,
      "matched_path": "SKILL.md"
    }
  ]
}
```

### `POST /skills/read`

Purpose:
- read one skill by exact name

Request:

```json
{
  "identity_id": "athena",
  "name": "context",
  "category": "shortlist"
}
```

Response:

```json
{
  "results": [
    {
      "name": "context",
      "category": "shortlist",
      "path": "/Users/zeus/Public/hydrai/skills/shortlist/context",
      "content": "# Skill text..."
    }
  ]
}
```

### `POST /skills/trusted-sites`

Purpose:
- list configured trusted skill hubs available for installation

Request:

```json
{}
```

Response:

```json
{
  "results": [
    {
      "id": "clawhub",
      "index_url": "https://example.com/skills/index.json",
      "site_url": "https://example.com/skills/",
      "description": "Trusted skill hub"
    }
  ]
}
```

### `POST /skills/install`

Purpose:
- install one skill from a trusted configured hub into `skills/user/`

Constraints:
- caller cannot pass arbitrary URLs
- `hub_id` must already exist in `Memory` config
- current v1 behavior is folder install only, with no post-install hooks

Request:

```json
{
  "identity_id": "athena",
  "hub_id": "clawhub",
  "skill_name": "git-helper",
  "force": false
}
```

Response:

```json
{
  "name": "git-helper",
  "category": "user",
  "path": "/Users/zeus/Public/hydrai/skills/user/git-helper",
  "hub_id": "clawhub",
  "version": "1.0.0"
}
```

## 5. Access Model

At the `Memory` level:

- sandbox-port callers can only access the associated sandbox
- control-port callers in system space can access all configured sandboxes

Finer permission logic such as identity-level read/write policy belongs above
`Memory`, normally in `Brain` and later `Nerve`.

## 6. Model Backends for ContexTree

`ContexTree`-backed features use sandbox-global backend defaults from
`Memory.json` under `context_defaults`, with optional per-resource override
through local `.PROMPT.json`.

On this machine, the current defaults are:

- text summary: `Intelligence :61102` local `qwen3-4b`
- image summary: `Intelligence :61101` local `qwen3-32b-vl`
- video summary: `Intelligence :61201` remote `qwen3.5-plus`
- embedding: `Intelligence :61100` local `bge-m3`

Per-resource `.PROMPT.json` may override:

- prompts
- route ports
- byte limits
