# Hydrai Memory Manual

This packaged manual is the runtime reference shipped with `hydrai-memory`.

Core surfaces:

1. `GET /health`
2. `GET /help`
3. `POST /brain/bootstrap`
4. `POST /resources/list`
5. `POST /tree/view`
6. `POST /tree/read`
7. `POST /tree/search`
8. `POST /tree/write`
9. `POST /tree/append`
10. `POST /tree/delete`
11. `POST /identity/relations`
12. `POST /identity/sessions`
13. `POST /identity/memorables-search`
14. `POST /session/recent`
15. `POST /session/search`
16. `POST /session/latest-attachments`
17. `POST /skills/list`
18. `POST /skills/search`
19. `POST /skills/read`
20. `POST /skills/trusted-sites`
21. `POST /skills/install`

`/brain/bootstrap` is the normal root-entry API for `Brain`.

Sandbox-port calls are actor-aware:

1. `actor_identity_id` is required for ongoing Brain tool calls
2. `session_id` is required for mounted `resource` access
3. `Memory` is the final gate for:
   1. session participant access
   2. mounted resource `ro` / `rw`
   3. self-only identity-tree access
   4. sandbox plus identity skill filtering

`/resources/list` returns the currently accessible targets for one actor,
including:

1. the actor's own identity-like root
2. all sessions the actor belongs to, with mode
3. mounted resources for the provided session, with mode

Request fields:

1. `actor_identity_id`
2. `requestor_id`
3. optional `session_id`
4. optional `query`
5. optional `top_k`
6. optional `min_score`
7. optional `attachment_limit`

Bootstrap returns:

1. `target_identity_id`
2. `requestor_id`
3. `requestor_persona`
4. `target_profile`
5. `friend_ids`
6. `session_ids`
7. optional `session`
8. `skill_shortlist`

`session`, when present, includes:

1. recent `context`
2. session `summary`
3. `participants`
4. mounted `resources`
5. `mounted_resources` with top-level summaries
6. `latest_attachments`
7. query-driven `search` hits

Sandbox-port calls are actor-aware, and `Memory` is the final gate for:

1. session participant access
2. mounted resource `ro` / `rw`
3. self-only identity-tree access
4. sandbox plus identity skill filtering

Normal skill visibility uses sandbox + identity filtering. Privileged capability
tokens such as `install_skill` are explicit-whitelist only.

Generic tree APIs operate on:

1. registered `resource`
2. `identity`
3. `session`
4. `human`
5. `native`

Skill shortlist entries in bootstrap contain the rendered `SKILL.md` text for
each shortlisted skill.

Security:

1. `HYDRAI_SECURITY_MODE=dev` bypasses internal auth
2. `HYDRAI_SECURITY_MODE=secure` requires Hydrai internal tokens

Config:

1. service config is normally `~/Public/hydrai/Memory.json`
2. `context_defaults` in that file define default Intelligence routes and prompts
3. per-resource `.PROMPT.json` may override prompts, route ports, and byte limits

For the full project copy of the manual and deeper examples, see the source-tree
`Memory/MANUAL.md` when available.
