# Hydrai Memory

`Memory` is Hydrai's durable state service.

It runs as one system-space process with:

1. one control port
2. one sandbox-facing port per sandbox

Startup:

```bash
hydrai-memory --config ~/Public/hydrai/Memory.json
```

Config:

- example: [`Configs/config.example.json`](/Users/zeus/Codebase/hydrai/Memory/Configs/config.example.json)

Control port:

1. `GET /health`
2. `GET /help`
3. `GET /sandboxes`
4. `GET/POST/DELETE /sandboxes/{sandbox_id}/...`

Sandbox port:

1. `GET /health`
2. `GET /help`
3. `POST /tree/...`
4. `POST /identity/...`
5. `POST /session/...`
6. `POST /skills/...`

Security:

1. `HYDRAI_SECURITY_MODE=dev` bypasses internal auth
2. `HYDRAI_SECURITY_MODE=secure` requires Hydrai internal tokens

The detailed architecture and API contract live in:

1. [`OVERVIEW.md`](/Users/zeus/Codebase/hydrai/Memory/OVERVIEW.md)
2. [`SPEC.md`](/Users/zeus/Codebase/hydrai/Memory/SPEC.md)
