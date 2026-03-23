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

## 8. Resource Registry

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

## 9. Service Dependency Rule

`Memory` should be a self-contained package.

Its allowed external service dependency is `Intelligence`, where model-backed
behavior is needed, for example:

1. embeddings
2. text summary generation
3. image/video summary generation later if retained

This keeps all storage semantics local to `Memory` while keeping model runtime
out of it.

## 10. Next Spec Stages

After this first slice, `Memory/SPEC.md` should next freeze:

1. `ContexTree` internal contract in more detail
2. `Resource` registry record schema
3. `IdentityState` layout and persona contract
4. `SessionBook` layout and session membership contract
5. `SkillSet` overlay and filtering contract
6. `Memory` control and sandbox-facing API inventory
