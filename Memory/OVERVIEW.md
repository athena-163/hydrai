# Hydrai Memory Overview

`Memory` is Hydrai's durable state authority.

It runs in system space as one process and owns the persisted truth for:

1. sandbox metadata
2. identity state
3. session state
4. skill registry and enablement
5. resource registry

`Memory` is the only Hydrai service that owns durable state by default, with the
top-level exception already defined in `TRUST.md` for `Nerve`'s pending-turn
cache.

## Role

`Memory` is the durable data body behind Hydrai.

Compared with AIOS, it absorbs and localizes what used to be spread across:

1. `ContexTree`
2. `SessionBook`
3. `AgentFile`, renamed in Hydrai to `IdentityState`
4. `SkillSet`
5. parts of `Gateway` identity/session/resource management

In Hydrai these are not shared repo-wide libraries. They live inside the
`Memory` service package and are managed there.

## Process Model

`Memory` is one system-space process.

It exposes:

1. one control/help port
2. one sandbox-facing port per sandbox

High-level port convention:

1. `62000` reserved for control/help by default
2. `62001-62999` reserved as the sandbox-facing band by default

These are conventions, not hardcoded constants. Final deployment should keep
the same shape but remain config-driven.

## Access Model

`Memory` has asymmetric access:

1. system-space services may access control and sandbox ports according to trust policy
2. a sandbox `Brain` may access only its associated sandbox-facing `Memory` port
3. sandbox processes other than the associated `Brain` must not call `Memory`

`62000` is the service-level control/help surface. It is not the normal
sandbox-facing data path.

## Durable Scope

`Memory` owns the persisted state for:

1. sandbox records and config
2. identity records and persona state
3. session records and books
4. skill availability and override state
5. resource registry records

It does not centralize the actual resource files themselves.

Resource content may live anywhere inside the sandbox user space, for example
under `/Users/<sandbox-user>/...`.

`Memory` only owns the registry and bookkeeping for those resources.

## Sandbox Layout

Given a configured root such as `~/Public/hydrai/`, the high-level durable
layout is:

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

Notes:

1. `skills/` is global at the root level
2. each sandbox can later enable or override subsets of the global skills
3. `resources.json` is a registry, not the resource content itself

## Identity Categories

Within each sandbox, all participants in session dialogue are treated as
identities through persona.

There are three important identity-like buckets:

1. `identities/`: normal sandbox identities
2. `human/`: human personas
3. `native/`: third-party agent systems represented through persona/manual state, such as Claude or Codex

This follows the AIOS scheme: session dialogue remains identity-to-identity at
the persona layer even when one participant is a human persona or a native
external system.

## Resource Model

Hydrai should prefer the domain word `resource` at the service/API boundary.

This is broader and clearer than overloading `context`.

`ContexTree` may still survive as an internal substrate concept inside
`Memory`, but the service contract should speak in terms of resource registry,
resource lookup, and resource attachment.

High-level rule:

1. resources are sandbox-scoped
2. resource files are not centralized under the system-space `Memory` root
3. `Memory` owns only the authoritative registry and metadata for them

## Relationship to Other Services

`Memory` serves:

1. `Brain`, which needs identity/session/resource/skill state to execute turns
2. `Nerve`, which needs sandbox/session/identity coordination data
3. `Introspect`, which needs admin/operator visibility and controlled mutation
4. future provisioning/control flows for sandbox lifecycle

`Memory` should not contain model-serving concerns. Its only external service
dependency should be `Intelligence`, where embedding or other model-backed
maintenance behavior is needed.

## Non-Goals for V1

The following should stay out of the initial top-level contract for now:

1. exact REST path inventory
2. exact on-disk file schemas for each durable primitive
3. exact skill-override resolution semantics
4. exact resource indexing and embedding maintenance behavior
5. exact sandbox creation workflow

Those belong in `Memory/SPEC.md`.
