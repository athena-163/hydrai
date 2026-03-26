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
- deployed root-level config: `~/Public/hydrai/Memory.json`

Control port:

1. `GET /health`
2. `GET /help`
3. `GET /sandboxes`
4. `GET/POST/DELETE /sandboxes/{sandbox_id}/...`

Sandbox port:

1. `GET /health`
2. `GET /help`
3. `POST /brain/bootstrap`
4. `POST /resources/list`
5. `POST /tree/...`
6. `POST /identity/...`
7. `POST /session/...`
8. `POST /skills/...`

`POST /brain/bootstrap` is the normal root-entry API for `Brain`.

Sandbox-port Brain calls are actor-aware. `Memory` is the final gate for:

1. session participant access
2. mounted resource `ro` / `rw`
3. self-only identity-tree access
4. sandbox plus identity skill filtering

Control-port tree and management APIs remain the system-space bypass surface.

Security:

1. `HYDRAI_SECURITY_MODE=dev` bypasses internal auth
2. `HYDRAI_SECURITY_MODE=secure` requires Hydrai internal tokens

ContexTree defaults:

1. global text/image/video/embedder routes and prompts live in `Memory.json` under `context_defaults`
2. individual resources may override prompts, route ports, and byte limits via local `.PROMPT.json`

Service templates:

1. macOS `launchd`: [com.hydrai.memory.plist.example](/Users/zeus/Codebase/hydrai/Memory/Deploy/launchd/com.hydrai.memory.plist.example)
2. Linux `systemd`: [hydrai-memory.service.example](/Users/zeus/Codebase/hydrai/Memory/Deploy/systemd/hydrai-memory.service.example)

The detailed architecture and API contract live in:

1. [`OVERVIEW.md`](/Users/zeus/Codebase/hydrai/Memory/OVERVIEW.md)
2. [`SPEC.md`](/Users/zeus/Codebase/hydrai/Memory/SPEC.md)
3. [`MANUAL.md`](/Users/zeus/Codebase/hydrai/Memory/MANUAL.md)

The installed package also ships a bundled runtime manual, so `/help` does not
depend on the source checkout being present.
