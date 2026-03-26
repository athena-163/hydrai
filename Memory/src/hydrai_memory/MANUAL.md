# Hydrai Memory Manual

This packaged manual is the runtime reference shipped with `hydrai-memory`.

Core surfaces:

1. `GET /health`
2. `GET /help`
3. `POST /brain/bootstrap`
4. `POST /tree/view`
5. `POST /tree/read`
6. `POST /tree/search`
7. `POST /tree/write`
8. `POST /tree/append`
9. `POST /tree/delete`
10. `POST /identity/relations`
11. `POST /identity/sessions`
12. `POST /identity/memorables-search`
13. `POST /session/recent`
14. `POST /session/search`
15. `POST /session/latest-attachments`
16. `POST /skills/list`
17. `POST /skills/search`
18. `POST /skills/read`
19. `POST /skills/trusted-sites`
20. `POST /skills/install`

`/brain/bootstrap` is the normal root-entry API for `Brain`.

Request fields:

1. `identity_id`
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
