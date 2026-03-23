# Hydrai Memory Spec

This document defines the `Memory` service contract in stages.

The first stage focuses on the root durable primitive inherited from AIOS:
`ContexTree`.

In Hydrai:

1. `ContexTree` remains an internal class name
2. the external mounted object and API/domain term should be `Resource`

## 1. Purpose

`Memory` is the single durable state service for Hydrai.

It owns:

1. sandbox records
2. identity state
3. session state
4. skill registry and skill enablement state
5. resource registry state

It does not own:

1. pending-turn cache owned by `Nerve`
2. model execution
3. tool execution
4. actual resource files that live in sandbox user space

## 2. Process Model

`Memory` is one system-space process.

It should expose:

1. one control/help port
2. one sandbox-facing port per sandbox

Current deployment convention:

1. `62000` as the default control/help port
2. `62001-62999` as the default sandbox-facing band

These are not hardcoded constants. They are config- and startup-driven.

## 3. Port Allocation Model

### 3.1 Control Port

`Memory` should load `control_port` from config.

That control surface may include:

1. `/help`
2. `/health`
3. sandbox port inventory discovery
4. management APIs

### 3.2 Sandbox Ports

The sandbox-to-port map should not be hardcoded in source.

Current direction:

1. `Nerve` or the trusted startup controller allocates the global sandbox-port map
2. that map is passed into `Memory` as startup configuration or startup parameters
3. each sandbox `Brain` receives only its associated sandbox-facing `Memory` port

This matches the runtime trust model already established for tokens.

## 4. Storage Root

Given a configured root such as `~/Public/hydrai/`, `Memory` owns the
system-space durable layout:

```text
root/
  skills/
  sandboxes/
    A/
      config.json
      human/
      native/
      identities/
      sessions/
      resources.json
```

Rules:

1. `skills/` is global
2. each sandbox owns its own durable subtree
3. `resources.json` is registry only
4. actual resource content stays in sandbox user space and is referenced by registry records

## 5. Vocabulary

Hydrai should use these domain terms:

1. `Resource`: external service/API noun for a mounted context-like object
2. `ContexTree`: internal implementation/substrate class name
3. `IdentityState`: Hydrai name replacing AIOS `AgentFile`
4. `SessionBook`: retained internal durable session primitive
5. `SkillSet`: retained internal skill discovery/registry primitive

This means:

1. users and other services mount `resources`
2. `Memory` may still internally back some resources with `ContexTree`
3. API paths and docs should prefer `resource`, not `context`, unless explicitly talking about AIOS compatibility

## 6. Identity Categories

Within a sandbox, session dialogue is always identity-to-identity at the persona
layer.

Durable identity-like categories are:

1. `identities/`: normal sandbox identities
2. `human/`: human personas
3. `native/`: third-party agent systems represented as identity-like participants with persona/manual state

Examples of `native/` entries:

1. `claude`
2. `codex`

The rule inherited from AIOS remains:

1. in session conversations, all participants are treated as identities by persona
2. `native/` represents continuity and persona/manual state, not provider runtime implementation

## 7. ContexTree as Internal Root Primitive

### 7.1 Why Start Here

`ContexTree` is the root durable content primitive because:

1. `SkillSet` is derived from it
2. resource indexing and semantic lookup are built on it
3. other higher-level durable layers depend on its file-tree and summary semantics

So `Memory` should first freeze how it adopts `ContexTree`.

### 7.2 Hydrai Role of ContexTree

In Hydrai, `ContexTree` should be treated as:

1. an internal managed tree abstraction
2. responsible for file-tree summaries, read views, and semantic lookup
3. attachable through registry-backed `Resource` entries

It should not itself become the top-level public service concept.

### 7.3 Resource vs ContexTree

A `Resource` record in `Memory` may point to:

1. a `ContexTree`-managed directory root in sandbox space
2. a plain file path
3. a website or external source later
4. another managed source type later

For v1, the important point is:

1. `Resource` is the registry/API abstraction
2. `ContexTree` is one internal implementation type behind some resources

### 7.4 ContexTree Ownership

`Memory` should own the `ContexTree` implementation internally rather than rely
on a shared repo-wide package.

The Hydrai-localized `ContexTree` should preserve the useful AIOS semantics:

1. directory-rooted managed tree
2. hidden items excluded
3. one summary metadata file per tracked folder
4. read/view/search operations over the managed tree
5. embedding-backed semantic search
6. safe path validation and bounded reads

### 7.5 ContexTree Scope in Memory V1

For the first `Memory` spec slice, the internal `ContexTree` contract should
cover:

1. managed root path
2. summary metadata layout
3. read API semantics
4. view API semantics
5. search API semantics
6. sync/update semantics

It should not yet freeze:

1. maintenance daemon behavior
2. background scheduling model
3. exact AI model prompts for summarization
4. exact API path inventory for all resource operations

### 7.6 Defaults and Overrides

Hydrai `ContexTree` should keep the same broad override model as AIOS:

1. global defaults configured by `Memory`
2. optional per-resource overrides
3. optional local `.PROMPT.json` overrides inside the managed tree

The important Hydrai correction is that route selection must be separated cleanly:

1. text summarization route
2. image summarization route
3. video summarization route
4. embedding route

The embedding route must not be implicitly derived from the text route.

In the current `ContexTree` port, local `.PROMPT.json` overrides may set:

1. prompt strings
2. route ports for `text`, `image`, `video`, `embedder`
3. per-resource byte limits for `text_max_bytes`, `image_max_bytes`, `video_max_bytes`

For secure mode outbound calls into `Intelligence`, `ContexTree` should not
guess among unrelated token ids.

Current implementation direction:

1. use one explicit outbound token pair for all `ContexTree -> Intelligence` calls, or
2. use a per-route token map keyed by target `Intelligence` port

### 7.7 Byte Limits

Hydrai `ContexTree` should split byte limits by modality.

At minimum:

1. text `max_bytes`
2. image `max_bytes`
3. video `max_bytes`

Semantics:

1. text may be truncated to `max_bytes`
2. image inputs must not be truncated
3. video inputs must not be truncated
4. oversized image/video inputs should be skipped or rejected for summarization rather than truncated

This applies both to direct summarize operations and to background maintenance.

Current implementation treats text limits as byte caps, not character counts.

### 7.8 Maintenance Ownership

Maintenance registration is an upper-level `Memory` decision, not a `ContexTree`
lib concern.

That means:

1. `ContexTree` should expose sync/maintenance-capable operations
2. `Memory` decides which resources are registered for maintenance
3. `Memory` owns scheduler state and lifecycle
4. Hydrai should replace AIOS detached per-root daemon processes with service-owned background threads or workers

## 9. Immediate Semantic Consistency

Foreground writer operations should not leave newly written files semantically
blank unless the file type is unsupported.

Current implementation direction:

1. `write_text` auto-summarizes if no explicit summary is provided
2. `append_text` auto-summarizes if no explicit summary is provided
3. `copy` auto-summarizes text, image, or video if supported and within limits
4. unsupported binaries may still remain without semantic summary until later policy handles them

## 10. Current ContexTree-Intelligence Mapping

The current live integration mapping used on this machine is:

1. text summarization -> local `qwen3-4b` on `61102`
2. image summarization -> local `qwen3-32b-vl` on `61101`
3. video summarization -> remote `qwen3.5-plus` on `61201`
4. embeddings -> local `bge-m3` on `61100`

This mapping is not hardcoded in `ContexTree`. It is carried by config and may
be overridden per resource.

## 11. Resource Registry

`Memory` should maintain a sandbox-local resource registry, likely in
`resources.json`.

At high level, each resource record should eventually capture:

1. `resource_id`
2. `type`
3. backing path or locator
4. ownership/sandbox scope
5. mount policy or access mode
6. optional managed-tree config reference

The registry owns metadata and bookkeeping only.

It does not relocate the actual resource content under the system-space root.

## 12. SessionBook

Hydrai should keep `SessionBook` as the durable session-log primitive, but with
cleaner domain language and clearer service ownership than AIOS.

The AIOS `SessionBook` core is mostly good. The important Hydrai work is to:

1. keep the append/rotate/query model
2. align terminology with Hydrai nouns
3. keep pending-turn state out of `SessionBook`
4. keep all implementation local to `Memory`

### 12.1 Role

`SessionBook` is the canonical durable log for one sandbox-local session.

It should own:

1. committed turn history
2. chapter segmentation and chapter summaries
3. session-level summary
4. session participant policy
5. session resource attachment policy
6. committed attachment registry/state inside the session root

It should not own:

1. pending confirm/retry/rewind state
2. routing decisions
3. model execution policy
4. native-provider continuity sidecars

Those remain upper-level concerns for `Nerve`, `Brain`, or future orchestration
layers.

### 12.2 Session Scope

Hydrai sessions are sandbox-local.

Rules:

1. one `SessionBook` belongs to one sandbox
2. a session may include identities, `human/`, and `native/` participants from that same sandbox
3. no session crosses sandbox boundaries

### 12.3 Durable Layout

The AIOS layout is still sound as a starting point:

```text
session_root/
  .SUMMARY.json
  config.json
  000000.log
  000001.log
  ...
  attachments/
    0001.jpg
    0002.pdf
```

Where:

1. `.SUMMARY.json` is ContexTree-managed semantic state
2. `config.json` is session metadata/policy
3. `NNNNNN.log` files are append-only chapters
4. `attachments/` stores committed imported files for that session

### 12.4 Hydrai Naming Cleanup

AIOS `SessionBook` uses `agents` and `mounted`.

For Hydrai, the clean external/domain language should be:

1. `identities` instead of `agents`
2. `resources` instead of `mounted`

Reason:

1. a session participant in Hydrai is always treated as an identity/persona
2. mounted context-like objects are now broadly `Resource`

Direction for Hydrai config shape:

```json
{
  "channel": "",
  "identities": {
    "zeus": "rw",
    "athena": "rw",
    "codex": "ro"
  },
  "resources": {
    "workspace-main": "rw",
    "reference-notes": "ro"
  },
  "brain": {},
  "attachments": {
    "next_serial": 1
  },
  "limits": {}
}
```

AIOS compatibility may still be handled during migration or load, but Hydrai
should not keep the older nouns as the preferred contract.

### 12.5 Permission Model

The AIOS two-axis permission idea should be kept.

Rules:

1. session participant mode is one axis: `ro` or `rw`
2. attached resource mode is another axis: `ro` or `rw`
3. effective write requires both axes to allow write
4. effective read requires participant presence plus resource presence

`SessionBook` stores this policy.
`Brain` or the higher execution layer computes/enforces the effective access at
runtime.

### 12.6 Chapters

The AIOS chapter model should be preserved.

Requirements:

1. chapters are zero-padded sequential `NNNNNN.log`
2. they are append-only plain text
3. turns are separated by `---`
4. the active chapter is the highest-numbered unsummarized chapter
5. closed chapters receive durable semantic summary state

### 12.7 Rotation And Recovery

The AIOS rotation model is good and should remain the basis for Hydrai.

Requirements:

1. auto-rotate when active chapter size reaches `max_chapter_bytes`
2. allow manual break only above `min_break_bytes`
3. deferred recovery is acceptable
4. recovery should summarize unsummarized non-active chapters
5. read-only calls should not trigger recovery implicitly

This fits Hydrai well because:

1. committed state stays durable and compact
2. session reads stay cheap
3. write paths already pay the summarization cost when needed

### 12.8 Query Model

The AIOS `query()` shape is also mostly correct.

The important contract is:

1. always return recent usable conversation context
2. combine prior summaries with recent raw turns under size budgets
3. optionally return semantic search results across summarized chapters
4. always return current participant/resource policy snapshot

Hydrai direction:

1. keep the recent-raw plus prior-summary budget model
2. keep optional semantic search over chapter summaries
3. rename returned config maps to `identities` and `resources`

### 12.9 Attachments

The AIOS attachment model is worth keeping with one important simplification.

Keep:

1. session-local `attachments/` folder
2. serial tag allocation through `attachments.next_serial`
3. marker injection into the chapter log
4. ContexTree-backed semantic summary state for attachments

Hydrai-specific interpretation:

1. attachment import becomes part of committed session state
2. attachment summaries belong only in ContexTree-managed `.SUMMARY.json`
3. no separate attachment sidecar metadata is needed in v1

Because Hydrai `ContexTree.copy()` now auto-summarizes supported file types when
no summary is supplied, the old AIOS async attachment-summary behavior is no
longer required as a default design requirement.

Hydrai direction:

1. `attach()` should commit the file and its marker in one durable operation
2. if summary is omitted, supported text/image/video files should gain semantic state immediately through ContexTree
3. oversized or unsupported binaries may remain without semantic summary
4. extra async enrichment should be treated as optional future optimization, not core correctness

### 12.10 Config Fields

At high level, `SessionBook/config.json` should carry:

1. `channel`
2. `identities`
3. `resources`
4. `brain`
5. `attachments`
6. `limits`
7. optionally a human-facing session `name`

Interpretation:

1. `channel` is opaque transport binding metadata
2. `brain` is opaque execution/worker metadata
3. `attachments.next_serial` is allocator state
4. `limits` overrides constructor/runtime defaults

### 12.11 Ownership Boundary With Nerve

This should be explicit in Hydrai:

1. committed conversation state belongs in `SessionBook`
2. pending unconfirmed turns belong outside `SessionBook`
3. confirm/retry/rewind state belongs outside `SessionBook`

That matches the Hydrai trust/control split already recorded at the top level.

### 12.12 Relationship To ContexTree

Hydrai `SessionBook` should still be built on top of the Hydrai-local
`ContexTree`.

That means:

1. chapter summaries live in ContexTree summary state
2. session summary lives in ContexTree summary state
3. attachment summaries live in ContexTree summary state
4. `view`, `read`, and semantic search may continue delegating to ContexTree where appropriate

### 12.13 What To Keep From AIOS

Keep:

1. chapter naming and append format
2. rotation and deferred recovery
3. budgeted `query()` assembly
4. session-local attachment serial allocation
5. ContexTree-backed summaries and search

### 12.14 What To Change For Hydrai

Change:

1. move implementation into `Memory`, not a shared repo-wide lib
2. rename external nouns from `agents`/`mounted` to `identities`/`resources`
3. make pending-turn state explicitly out of scope
4. treat immediate semantic consistency for attachments as the default expectation
5. keep service/API language aligned with Hydrai's sandbox-local session model

## 13. Service Dependency Rule

`Memory` should be a self-contained package.

Its allowed external service dependency is `Intelligence`, where model-backed
behavior is needed, for example:

1. embeddings
2. text summary generation
3. image/video summary generation later if retained

This keeps all storage semantics local to `Memory` while keeping model runtime
out of it.

## 14. Next Spec Stages

After this first slice, `Memory/SPEC.md` should next freeze:

1. `ContexTree` internal contract in more detail
2. `Resource` registry record schema
3. `IdentityState` layout and persona contract
4. `SessionBook` layout and session membership contract
5. `SkillSet` overlay and filtering contract
6. `Memory` control and sandbox-facing API inventory

## 15. IdentityState

Hydrai should replace AIOS `AgentFile` with `IdentityState`.

The underlying idea is still good: one durable root per identity that stores
its self-model, relationship state, session-scoped ongoing notes, memorable
episodes, and impulse definitions.

### 15.1 Role

`IdentityState` is the canonical durable state container for one sandbox-local
identity.

It should own:

1. the identity's private core self-description
2. the identity's outward persona/presentation
3. relationship state toward other identities
4. session-scoped ongoing notes
5. memorable long-term notes
6. impulse definitions or impulse-local config records
7. identity-local config metadata

It should not own:

1. live model/runtime process state
2. pending turn state
3. session transcript history
4. cross-sandbox identity state

### 15.2 Naming

Hydrai should stop using `AgentFile` as the primary term.

Canonical Hydrai term:

1. `IdentityState`

Reason:

1. Hydrai uses `identity` consistently across sandbox/session design
2. `AgentFile` is AIOS-specific and too narrow for human/native identity-like actors

### 15.3 Scope

One `IdentityState` belongs to one sandbox and one identity-like entity.

That entity may be:

1. a normal sandbox identity
2. a `human/` persona
3. a `native/` third-party agent persona/manual state

The storage primitive can stay the same across all three categories even if
their higher-level orchestration differs.

### 15.4 Durable Layout

The AIOS structure is still a good starting point:

```text
identity_root/
  config.json
  identity/
    SOUL.md
    PERSONA.md
  dynamics/
    self.md
    other-identity.md
  ongoing/
    <session_id>.md
  memorables/
    0001.title.md
  impulses/
    name.json
```

Hydrai interpretation:

1. `identity/SOUL.md` is private internal self-state
2. `identity/PERSONA.md` is the outward social/role expression
3. `dynamics/` stores subjective relationship state
4. `ongoing/` stores session-scoped working continuity
5. `memorables/` stores accumulated memorable notes
6. `impulses/` stores impulse definitions or opaque impulse payloads

Hydrai refinement:

1. for normal identities, the full structure may be used
2. `human/` and `native/` records may stay much lighter at the `Memory` top level
3. those lighter categories do not need to force full `IdentityState` semantics in v1

### 15.4.1 SOUL vs PERSONA

This should be explicit in Hydrai:

1. `SOUL.md` is self-only internal state
2. `PERSONA.md` is the outward presentation layer
3. when one identity needs another identity's social representation, higher layers should load `PERSONA.md`, not `SOUL.md`
4. `Brain` may load both for the identity it is executing as

### 15.4.2 Dynamics Self File

Hydrai should keep the AIOS convention of a reserved self-dynamics file.

Direction:

1. use `self.md`
2. treat it as the reserved self-reflection/self-state relationship file
3. `get_friends()` should exclude it

`self.md` is clearer and more stable than `me.md` because it reads as a stable
system noun instead of a speaker-relative pronoun.

### 15.5 Typed Surface

The AIOS typed API shape is mostly worth keeping.

Hydrai `IdentityState` should likely expose typed operations for:

1. `soul()` / `set_soul()`
2. `persona()` / `set_persona()`
3. `dynamic(name)` / `set_dynamic(name, content)`
4. `ongoing(session_id)` / `set_ongoing(session_id, content)`
5. `memorable(name)` / `add_memorable(title, content)`
6. `impulse(name)` / `set_impulse(name, content)` / `delete_impulse(name)`
7. list helpers such as `get_impulses()`, `get_sessions()`, `get_friends()`

This is a good fit because those storage areas are semantically distinct and
very stable.

### 15.6 Config

AIOS mostly treated `config.json` as opaque storage with one notable runtime
section for skill filtering.

Hydrai should keep the same high-level stance:

1. `config.json` is mostly opaque to `IdentityState`
2. higher layers may reserve specific stable subtrees in it

The main currently known reserved subtree is skill filtering policy.

Hydrai direction:

```json
{
  "skills": {
    "whitelist": [],
    "blacklist": []
  }
}
```

Rules inherited from AIOS:

1. filtering is by skill name
2. empty whitelist means allow all by default
3. non-empty whitelist restricts to listed skills
4. blacklist is subtractive

This should stay a coarse capability filter, not the place where fine-grained
session resource permission is enforced.

### 15.7 Relationship To SessionBook

`IdentityState` and `SessionBook` should remain separate.

Division:

1. `SessionBook` owns committed shared session history
2. `IdentityState.ongoing/<session>.md` owns that identity's session-local continuity notes

This separation is important and should be preserved in Hydrai.

Hydrai refinement:

1. `ongoing/` is keyed strictly by `session_id`
2. it should be treated as the set of session-local continuity notes for all involved sessions of that identity

### 15.8 Relationship To ContexTree

Like AIOS `AgentFile`, Hydrai `IdentityState` should likely still be built on
top of the Hydrai-local `ContexTree`.

That gives:

1. typed file wrappers over a managed semantic tree
2. built-in `view`, `read`, and search behavior
3. summary/vector freshness through explicit `sync()`

### 15.9 Query Model

The AIOS `query()` pattern is a good starting point.

High-level return shape should include:

1. `soul`
2. `persona`
3. a structural `view`
4. optional session-specific `ongoing`
5. optional semantic `results`

Rules:

1. `query()` should require either `query_embed` or `query_text`
2. `results` should not be returned for a query-less call
3. if both are supplied, `query_embed` wins

Search should focus on:

1. `memorables/`
2. `dynamics/`
3. `ongoing/`

It should not waste query bandwidth on:

1. `config.json`

Hydrai clarification:

1. `impulses/` remains part of the durable identity tree
2. impulse files may appear in the structural `view`
3. what is deferred is the impulse file schema and higher-level semantics, not its existence in the tree

### 15.10 Evolve Path

The AIOS `evolve()` batch-write pattern is useful and should probably remain.

Purpose:

1. batch durable self-updates after reflection/evolution work
2. write memorables, dynamics, and ongoing changes together
3. run a full `sync()` afterward so semantic search is fresh

This fits Hydrai well because `Impulse` is an explicit service and will likely
need exactly this kind of durable identity-update path later.

Rules:

1. `evolve()` is additive/update-only
2. `evolve()` should not imply delete semantics in v1

### 15.10.1 Memorables Titles

One point worth locking for implementation:

1. callers should not need to pre-sanitize memorable titles
2. `add_memorable(title, content)` should normalize the title into a safe filename slug
3. the stored filename still keeps the serial prefix form: `0001.safe-title.md`

This is cleaner than forcing every caller to pass an already filesystem-safe token.

### 15.10.2 Impulses

Impulse payload schema is intentionally deferred.

For now:

1. `impulses/` remains part of `IdentityState`
2. impulse files remain part of the visible tree/view surface
3. detailed impulse payload schema and execution semantics should be designed with the `Impulse` service later
4. `IdentityState` may still expose simple raw-file helpers without interpreting schema

### 15.11 What To Keep From AIOS

Keep:

1. the five-bucket structure: identity/dynamics/ongoing/memorables/impulses
2. `SOUL.md` and `PERSONA.md`
3. memorable serial naming
4. ongoing state keyed by session id
5. typed wrappers plus generic inherited tree operations
6. batch `evolve()` concept

### 15.12 What To Change For Hydrai

Change:

1. rename the concept to `IdentityState`
2. keep the implementation local to `Memory`
3. make the abstraction explicitly valid for normal, human, and native identity-like records
4. align docs and API language with `identity`, not `agent`
5. keep config mostly opaque while documenting the skill-filter subtree clearly
6. treat `SOUL` as self-only and `PERSONA` as outward-facing
7. normalize memorable titles instead of requiring pre-sanitized tokens
8. leave impulse schema and execution semantics deferred to the `Impulse` service design

## 16. SkillSet

Hydrai should keep `SkillSet` as the internal skill discovery primitive, with
the same core role as AIOS but localized inside `Memory`.

### 16.1 Core Role

`SkillSet` is:

1. a thin wrapper around a skill root
2. compatible with the OpenClaw on-disk skill format
3. built on top of Hydrai-local `ContexTree`
4. responsible for discovery, prompt rendering, and optional default-skill deployment

`SkillSet` is not:

1. a runtime skill executor
2. a policy engine for sandbox or identity visibility
3. a replacement for `Brain` tool registration

### 16.2 OpenClaw Compatibility

Hydrai should preserve the OpenClaw skill folder format as the canonical skill
format.

That means:

1. one folder per skill
2. required `SKILL.md` at the skill root
3. optional YAML frontmatter in `SKILL.md`
4. markdown body in `SKILL.md`
5. optional support folders such as `scripts/`, `references/`, `assets/`, `bin/`, or `src/`

Hydrai should not invent a second incompatible skill package format.

### 16.3 Storage Position

At the `Memory` root, skills are global:

1. `root/skills/`

Within that global root, category layout such as:

1. `shortlist/`
2. `builtin/`
3. `user/`

is a caller-level convention rather than a `SkillSet` internal requirement.

`SkillSet` should operate on any caller-provided root path.

### 16.4 Relationship To ContexTree

`SkillSet` should continue to use `ContexTree` as its substrate because:

1. skills are mostly text documents and small support files
2. semantic search over `SKILL.md` and `references/` is useful
3. `ContexTree.view(...)` is a natural listing basis
4. `ContexTree.search_by_text(...)` is a natural semantic search basis

Important boundary:

1. OpenClaw skill layout remains the on-disk truth
2. `SkillSet` should not impose any new tree structure
3. `SkillSet` should remain thin rather than becoming a second tree manager

### 16.5 Public Python Surface

Initial public Python API should stay minimal.

#### `list_skills(root, depth=2, summary_depth=2)`

List all skills under one root.

Behavior:

1. prefer `ContexTree.view(...)`
2. detect skills by locating `SKILL.md`
3. return one entry per enclosing skill root
4. use `SKILL.md` semantic summary when available
5. fall back to frontmatter `description` when semantic summary is absent

Expected fields:

1. `name`
2. `path`
3. `summary`

#### `search_skills(root, query, limit=10, min_score=0.3)`

Search one root for relevant skills.

Behavior:

1. require non-empty `query`
2. prefer semantic search through `ContexTree.search_by_text(...)`
3. allow matches in `SKILL.md` and nested files like `references/*`
4. resolve each match back to the enclosing skill root
5. deduplicate by skill root
6. fall back to deterministic text search when semantic search is unavailable or empty

Expected fields:

1. `name`
2. `path`
3. `summary`
4. `score`
5. `matched_path`

#### `render_prompt(skill_paths)`

Render deterministic prompt blocks for already-resolved skill roots.

Behavior:

1. load `SKILL.md` from each provided root
2. parse frontmatter when present
3. include skill name, root path, optional description, and markdown body
4. not apply category or access policy

#### `deploy_defaults(root, categories=("shortlist", "builtin"))`

Deploy packaged default skills into a caller-provided root.

Behavior:

1. create the target root when needed
2. copy packaged `shortlist/` and `builtin/` skill trees into that root
3. not overwrite an existing category directory
4. report created and skipped categories

`initialize(...)` may remain an alias for `deploy_defaults(...)`.

### 16.6 Ownership Boundary

`SkillSet` should do:

1. skill discovery
2. semantic and deterministic search
3. skill prompt rendering
4. packaged default-skill deployment

`SkillSet` should not do:

1. identity-level allow/deny filtering
2. sandbox-level skill overlays
3. runtime execution
4. access control
5. shortlist policy decisions

Those remain higher-level `Memory` or `Brain` concerns.

### 16.7 What To Keep From AIOS

Keep:

1. exact OpenClaw-compatible `SKILL.md` folder shape
2. thin wrapper model over `ContexTree`
3. list/search/render/deploy core surface
4. packaged `shortlist` and `builtin` seed skills
5. deterministic text-search fallback

### 16.8 What To Change For Hydrai

Change:

1. keep the implementation local to `Memory`
2. use Hydrai-local `ContexTree`, not an external shared library
3. treat global `root/skills/` as the durable system-space storage root
4. keep identity and sandbox visibility filtering outside the `SkillSet` library

## 17. Service-Layer Assembly Rough Picture

With the four internal durable primitives now in place:

1. `ContexTree`
2. `SessionBook`
3. `IdentityState`
4. `SkillSet`

the remaining `Memory` work is the service layer that owns and coordinates them.

At a rough level, that service layer should cover:

1. `Resource` registry and maintenance
2. identity management
3. session management
4. `Brain`-facing tool APIs

### 17.1 Resource

`Resource` should be the simplest service-layer wrapper and should come first.

At a rough level it owns:

1. the sandbox-local registry of known resources
2. mapping from stable `resource_id` to real sandbox-space paths
3. managed-resource maintenance registration and status
4. the distinction between registry-only resources and `ContexTree`-managed resources

It does not own:

1. the resource files themselves
2. per-session mount policy

### 17.2 Identity Management

Identity management should own:

1. create/update/list/read of normal identities
2. create/update/list/read of lighter `human/` and `native/` entries
3. top-level persona/config handling for those lighter categories
4. identity skill overlay state

Normal identities should be backed by `IdentityState`.

Lighter `human/` and `native/` entries may stay simpler at the top `Memory`
layer and should not be forced into the full `IdentityState` shape in v1.

### 17.3 Session Management

Session management should own:

1. create/update/list/read of sandbox-local sessions
2. membership and mount mutation for sessions
3. one `SessionBook` per session
4. session-local attachment import and query surfaces

It does not own:

1. pending confirm/retry/rewind state

That remains a `Nerve` responsibility.

### 17.4 Brain-Facing Tool APIs

`Memory` should expose stable noun-based tool APIs for `Brain`.

At a rough level these should cover:

1. resource list/read/view/search and later write where policy allows
2. session query/append/attach and related metadata access
3. identity query/evolve and typed state operations
4. skill list/search/read

`Brain` should not manipulate system-space files directly.

### 17.5 Ownership Split

At a rough level the ownership split should remain:

1. `Memory` owns durable truth
2. `Nerve` owns routing and pending-turn cache
3. `Brain` owns execution logic only

## 18. Resource Registry And Maintenance

Hydrai should adopt the useful split from AIOS `Gateway`:

1. a sandbox-local global resource registry
2. separate per-session mounts stored in `SessionBook`

External term:

1. `Resource`

Internal lineage:

1. AIOS `context block`
2. internal `ContexTree` where applicable

### 18.1 Core Role

The `Resource` layer should own:

1. stable sandbox-local `resource_id` registration
2. metadata for each registered resource
3. optional maintenance policy for managed resources
4. status/reporting for those managed resources

The `Resource` layer should not own:

1. per-session mount state
2. identity membership policy
3. the actual resource file contents

### 18.2 Storage Position

Per sandbox:

1. `root/sandboxes/<sandbox>/resources.json`

That file is registry only.

Actual resource content remains in sandbox space, for example under
`/Users/<sandbox-user>/...`.

### 18.3 Registry Shape

Hydrai should keep the same broad AIOS idea:

1. one stable id per registered resource
2. each id maps to one configured root or path
3. maintenance policy belongs to the registry, not inside the resource tree

Directionally, the sandbox-local registry should look like:

```json
{
  "default_maintain_interval_sec": 300,
  "resources": {
    "workspace-main": {
      "type": "context_tree",
      "root": "/Users/olympus/workspace/main",
      "config_path": "/Users/zeus/Public/hydrai/Memory.json",
      "maintain_interval_sec": null
    }
  }
}
```

Fields:

1. `default_maintain_interval_sec`: sandbox default for managed-resource maintenance
2. `resources[resource_id].type`: internal handling type such as `context_tree`, `file`, or future types
3. `resources[resource_id].root`: absolute sandbox-space root or file path
4. `resources[resource_id].config_path`: optional config path for managed tree behavior
5. `resources[resource_id].maintain_interval_sec`: optional per-resource override; `0` disables maintenance for that resource

### 18.4 V1 Resource Types

For v1, `Memory` should primarily care about:

1. `context_tree`
2. maybe plain `file` later if needed

The important point is not to over-expand the type system yet.

### 18.5 Managed vs Registry-Only

Hydrai should distinguish:

1. registry-only resources
2. managed resources

A managed resource means:

1. `Memory` knows how to open it through one internal substrate such as `ContexTree`
2. `Memory` may maintain summaries and semantic search state for it
3. `Memory` may report maintenance status for it

A registry-only resource means:

1. the id and path are known
2. richer maintenance or semantic operations may be unavailable

### 18.6 Maintenance Ownership

Hydrai should keep the useful AIOS rule that operational maintenance policy
lives in the registry, not inside `.PROMPT.json`.

That means:

1. global default maintenance interval is registry state
2. per-resource maintenance override is registry state
3. local `.PROMPT.json` remains for summary/model/prompt overrides only

### 18.7 Maintenance Execution Model

Unlike AIOS detached daemons, Hydrai should run maintenance inside the
`Memory` service process.

So:

1. registry records decide whether maintenance is desired
2. `Memory` owns the worker-thread scheduler
3. `Memory` reconciles actual running maintenance workers against desired policy

### 18.8 Relationship To Session Mounts

Per-session mount state should remain separate.

That means:

1. the registry answers what resources exist in the sandbox
2. `SessionBook` answers which resource ids are mounted in one session and with what mode

This is the same useful split AIOS had between:

1. global context registry
2. per-session mounted context policy

### 18.9 Brain-Facing Use

At a rough level, `Brain` should eventually receive:

1. resource id
2. resource type
3. top-level summary when available
4. only the resource ids actually mounted or otherwise allowed for that session

By default prompt-facing systems should prefer resource ids and summaries rather
than raw absolute paths.

### 18.10 Initial Library Surface

The current `Memory` implementation should expose two internal library surfaces
before the full HTTP service exists:

1. `ResourceRegistry`
2. `MemorySandboxAPI`

`ResourceRegistry` should own:

1. register
2. unregister
3. get
4. list
5. default maintenance interval update
6. maintenance reconciliation

`MemorySandboxAPI` should own generic file-tree operations over sandbox-scoped
targets.

### 18.11 Initial Sandbox API Shape

The current generic target families should be:

1. `resource`
2. `identity`
3. `session`
4. optionally `human`
5. optionally `native`

The initial generic operations should be:

1. `view`
2. `search`
3. `read`
4. `write`
5. `append`
6. `delete`

Read-only operations should work for:

1. registered resources
2. identity folders
3. session folders

Write operations may also work over those same tree-backed targets.

### 18.12 Access Boundary At This Layer

At this `Memory` library layer, policy should remain intentionally narrow.

This layer should enforce:

1. a sandbox-scoped caller may only access its associated sandbox durable subtree
2. a sandbox-scoped caller may only access registered resource roots that stay inside its associated sandbox-space path
3. a system-space caller may access any sandbox

This layer should not enforce:

1. per-session mounted-resource policy
2. identity visibility policy
3. writable-vs-readonly session semantics

Those are higher-level `Brain` or service-control concerns.
