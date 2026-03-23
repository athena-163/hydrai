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

Search should focus on:

1. `memorables/`
2. `dynamics/`
3. `ongoing/`

It should not waste query bandwidth on:

1. `config.json`
2. `impulses/`

### 15.10 Evolve Path

The AIOS `evolve()` batch-write pattern is useful and should probably remain.

Purpose:

1. batch durable self-updates after reflection/evolution work
2. write memorables, dynamics, and ongoing changes together
3. run a full `sync()` afterward so semantic search is fresh

This fits Hydrai well because `Impulse` is an explicit service and will likely
need exactly this kind of durable identity-update path later.

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
