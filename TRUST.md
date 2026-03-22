# Hydrai Trust Model

This document records the top-level trust scheme for Hydrai and should guide all
later service design.

It is intentionally high level. Service-specific details belong in each
module's `SPEC.md`, but they should conform to the rules here.

## 1. Core Trust Boundary

Hydrai assumes a strict trust split:

1. system space is trusted
2. sandbox space is lower-trust

Interpretation:

1. system-space services are part of Hydrai's trusted control and integration layer
2. sandbox processes are not trusted by default
3. the sandbox `Brain` is the only sanctioned caller from sandbox into system-space services
4. a sandbox failure is expected to be contained within that sandbox boundary

Unix-user separation provides containment, but it is not sufficient by itself
for service trust. Internal service calls still require explicit authentication.

## 2. Service Access Rules

Top-level call rules:

1. `Nerve` is the only trusted ingress into a sandbox `Brain`
2. sandbox `Brain` is the only sanctioned caller from sandbox into system-space services
3. system-space services must not trust arbitrary localhost or same-host callers
4. `Peripheral` must not call sandbox `Brain` directly except through `Nerve`
5. `Intelligence`, `Toolbox`, and protected `Memory` endpoints should only accept authenticated internal callers

This keeps the service mesh explicit instead of relying on machine locality or
shared code assumptions.

## 3. Token Model

Hydrai uses runtime-issued internal service tokens.

High-level rules:

1. tokens are issued at runtime, not committed into repository config
2. tokens are injected into services during startup or controlled runtime provisioning
3. tokens are directional and scoped, not one global shared secret
4. token validity alone is not enough; the token's scope also defines what it may call

Examples of directional scope:

1. `Nerve -> Brain`
2. `Brain -> Intelligence`
3. `Brain -> Toolbox`
4. `Brain -> Memory`
5. `Peripheral -> Nerve`
6. `Introspect -> *` with separate admin scope

The exact header format and validation mechanism are deferred to later detailed
specs, but every protected service boundary should follow one Hydrai-wide
internal auth scheme.

## 4. Memory-Only Secret Rule

Internal service tokens should remain in memory.

Default rule:

1. do not store active internal tokens in normal files
2. do not treat repository config as a trust-material store
3. do not persist live token sets as ordinary durable state
4. services should receive only the subset of tokens they actually need

Reasoning:

1. avoids casual file peeking of live trust material
2. keeps trust tied to a runtime, not to static machine config
3. reduces spillover if one component is inspected later

This means token state is part of the live runtime, not part of normal durable
application data.

## 5. Nerve As Trust Authority

At the current architectural level, `Nerve` is the runtime trust authority.

Meaning:

1. Hydrai bootstraps with an initial token set
2. `Nerve` holds the authoritative in-memory view of the active token set
3. if future runtime sandbox creation is supported, `Nerve` is responsible for issuing or assigning the needed sandbox-scoped tokens
4. token add/update flows should be treated as control-plane operations, not normal business APIs

This keeps trust issuance centralized and aligned with `Nerve`'s role as the
master routing/orchestration service.

## 6. Trust Epoch

One running `Nerve` lifetime defines one active trust epoch.

Within a trust epoch:

1. all participating services use the same active token universe
2. service-to-service trust is coherent because all services were started or updated under that same authority

This concept matters because internal tokens are memory-only. Once the trust
authority disappears, the runtime can no longer safely assume its token view is
still authoritative.

## 7. Restart Rules

Hydrai should follow these restart rules.

### 7.1 Non-`Nerve` Service Restart

If a non-`Nerve` service goes down:

1. `Nerve` may restart it with the same current token subset relevant to that service
2. this is valid because the trust epoch is still alive
3. other services still hold the current token set in memory

This applies to services such as:

1. `Intelligence`
2. `Toolbox`
3. `Memory`
4. `Peripheral`
5. `Introspect`
6. a sandbox `Brain`

### 7.2 `Nerve` Restart

If `Nerve` goes down:

1. the authoritative in-memory token state is lost
2. surviving services may still hold old tokens
3. trust state is no longer safely reconstructable from the live mesh alone

Therefore the rule is:

1. if `Nerve` restarts, Hydrai should restart all trust-participating services
2. the restarted runtime should receive a fresh token set
3. this begins a new trust epoch

This is the preferred early-stage model because it is much cleaner than trying
to partially recover or merge token state across processes.

## 8. Runtime Provisioning For Future Sandboxes

If Hydrai later supports runtime sandbox creation:

1. startup-only token issuance is not sufficient by itself
2. `Nerve` must be able to provision new sandbox-scoped trust at runtime
3. this should happen through narrow control-plane operations
4. this should not become a general open-ended token mutation API

High-level direction:

1. bootstrap trust at platform start
2. let `Nerve` extend trust state for newly created sandboxes during the same trust epoch

## 9. Bring-Up / Testing Mode

Hydrai should support a low-friction local bring-up mode.

Recommended rule:

1. if internal auth material is not provided at startup, services may run in an explicit insecure development mode
2. in that mode, protected internal endpoints are open for local testing and bring-up
3. this mode must be clearly labeled insecure and must not be the default for serious deployment

Important constraint:

1. this should be an explicit runtime mode, not an accidental silent fallback

So the preferred behavior is not merely "no tokens means free to call."
Instead:

1. introduce a clear mode distinction such as `dev` versus `secure`
2. in `dev`, internal auth checks are bypassed intentionally
3. in `secure`, missing required auth material is a startup error

This preserves easy testing without allowing ambiguous half-secure behavior.

## 10. Design Guidance For All Services

All later service specs should follow these rules:

1. never assume same-machine callers are automatically trusted
2. protect internal endpoints with the shared Hydrai internal auth scheme
3. keep provider keys and other privileged credentials in system space only
4. give sandbox `Brain` only the narrow tokens it actually needs
5. treat trust-management operations as control-plane actions
6. design for memory-only active tokens
7. respect the trust-epoch restart rule centered on `Nerve`
8. support explicit insecure bring-up mode only as a deliberate development choice

## 11. Status

This document is the current top-level trust reference for Hydrai.
It should be used to guide the detailed design of `Nerve`, `Brain`,
`Intelligence`, `Toolbox`, `Memory`, `Peripheral`, and `Introspect`.
