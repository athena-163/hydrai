# Hydrai Overview

Hydrai is a local-first multi-service AI agent platform designed to run on either:

1. a Mac
2. an Ubuntu server or device, including GPU-capable systems such as DGX Spark

Hydrai is organized as one body made of multiple Python services. The intended shape is a
"multi-brain AI creature": distinct runtime partitions cooperate through explicit service
boundaries instead of collapsing into one monolith.

## Execution Model

Hydrai is split into:

1. system space
2. multiple sandbox spaces

System space is the privileged host layer. Sandbox spaces are lower-trust execution domains.

Working host model:

1. the root host user, such as `/Users/zeus` on this Mac, is the system space
2. system space can see sandbox users and manage the whole machine
3. sandbox users cannot write into system space
4. system space may selectively allow limited read access to sandbox users where needed

Current direction:

1. one `Brain` instance runs inside each sandbox
2. all other core services run in system space
3. each sandbox may contain many identities
4. sessions occur among identities within the same sandbox

This preserves a core AIOS idea:

1. privileged integrations stay outside sandbox execution
2. cognition/execution inside sandboxes remains separated from secrets and system-level mutation paths

## Hierarchy

Hydrai currently assumes a strict hierarchy:

1. system space
2. sandbox
3. identity and session

Interpretation:

1. system space is the trusted host-control layer
2. each sandbox is an isolated Unix user environment
3. identities and sessions live inside a sandbox, not across sandboxes

Example mental model:

1. a business deployment may assign one sandbox per client
2. that client can build its own world, identities, and sessions freely inside that sandbox
3. nothing in that sandbox should directly affect another sandbox

## Architectural Partitions

The folders under `hydrai/` are the primary body partitions of Hydrai.

### Brain

Runs in sandbox space, one instance per sandbox.

Responsibilities:

1. execute identity cognition/runtime logic
2. coordinate identity-level reasoning and actions within the sandbox
3. operate without direct ownership of privileged system credentials
4. remain intentionally lean compared with the older AIOS `Brain`
5. remain stateless across requests

Working model:

1. `Brain` receives a request
2. finds the necessary contexts and inputs
3. loops through model, skill, and tool usage until completion
4. returns results without becoming an owner of durable state

### Intelligence

Runs in system space.

Comparable to the model-forwarding part of `aios/Proxy`.

Responsibilities:

1. wrap real AI model providers and model runtimes
2. expose each model route on separate ports or endpoints
3. isolate provider-specific credentials and connection details from sandboxed `Brain` instances
4. remain stateless and maximize parallel request handling

### Toolbox

Runs in system space.

Comparable to the external-tools side of `aios/Proxy`.

Responsibilities:

1. wrap external tools such as web search, email, and similar integrations
2. broker credentialed tool access for sandboxes
3. enforce policy and permission boundaries around tool usage
4. remain stateless and maximize parallel request handling

### Memory

Runs in system space.

Responsibilities:

1. manage system-level data and durable records
2. store identity states
3. store session books
4. store skill sets
5. maintain resource registry and related metadata
6. act as the sole owner of durable state across Hydrai

### Peripheral

Runs in system space.

Comparable to `aios/Channel`.

Responsibilities:

1. bridge human-facing interfaces such as Telegram
2. normalize inbound/outbound interaction across channels
3. preserve identity and session context when handing traffic into Hydrai

### Nerve

Runs in system space.

Comparable to the planned AIOS gateway.

Responsibilities:

1. route traffic between sessions and identities
2. coordinate session flow across the platform
3. act as the central request-routing and orchestration layer
4. serve as the only trusted entry point into each sandbox `Brain`

Allowed temporary exception:

1. `Nerve` may keep a cached pending chat turn per session
2. this supports flows such as waiting for human confirmation or rewind
3. this cache is operational state, not the durable system of record

### Impulse

Runs in system space.

Responsibilities:

1. provide heartbeat-like drives to identities
2. represent purpose, initiative, and internal activation logic
3. trigger self-to-self conversations beyond direct user-request/response loops
4. run as one or more cron-like jobs with different purposes

This is currently a distinct Hydrai concept, not just a renamed AIOS component.

### Introspect

Runs in system space.

Responsibilities:

1. provide a dashboard for observing Hydrai internals
2. allow inspection of identity, session, and service state
3. allow controlled modification of internal states

## Current System Shape

At a high level:

1. `Peripheral` receives external interaction
2. `Nerve` routes requests to the correct session and identities
3. sandbox `Brain` instances execute identity-side cognition
4. `Intelligence` serves model access
5. `Toolbox` serves external tool access
6. `Memory` stores durable system-level state
7. `Impulse` provides ongoing drives / heartbeats
8. `Introspect` exposes operational visibility and state control

## Boundary Rules

Hydrai aims for very clean service boundaries.

Top-level principle:

1. services should not depend on shared internal libraries or blurred code ownership
2. each service should have a narrow contract and independent responsibility
3. services should be replaceable or evolvable one by one without repeated cross-service rewrites
4. durable state ownership should remain centralized instead of leaking across services

This matters because the intended development model is to attack each service independently after the top-level contracts are clear.

## Trust Model

Working trust model:

1. services in system space are trusted
2. sandbox space is lower-trust by design
3. each sandbox `Brain` may act freely inside its own sandbox
4. the worst acceptable sandbox failure is damage contained within that sandbox

State model:

1. `Memory` owns durable state
2. `Nerve` may hold limited pending-turn cache state for session control flows
3. `Brain` is stateless

Access rules:

1. a sandbox `Brain` only accepts inbound access from `Nerve`
2. calls from sandbox to system-space services must come from that sandbox's associated `Brain`
3. system-space services should not expose privileged operations directly to arbitrary sandbox processes
4. trust and authorization among services must be explicit, similar in spirit to AIOS

## Naming Direction

Hydrai intentionally uses organism-style partitions instead of generic service names.

Working interpretation:

1. `Brain` is sandbox cognition
2. `Nerve` is routing and coordination
3. `Peripheral` is external sensory / interface bridge
4. `Memory` is durable recall and registry
5. `Impulse` is initiative and drive
6. `Introspect` is self-observation and operator dashboard
7. `Intelligence` is model access
8. `Toolbox` is external capability access

## Key Inherited Principles From AIOS

Hydrai currently appears to inherit and retain these important principles:

1. strict separation between sandbox cognition and privileged system-space integrations
2. explicit service boundaries
3. credentials kept outside sandbox space
4. session-aware routing/orchestration
5. support for multiple identities and sessions instead of a single-agent runtime
6. explicit trust/authentication between protected service boundaries

## Open Design Questions

These points still need to be made explicit in future docs/specs:

1. how strict service independence should be enforced in practice if code sharing is intentionally minimized
2. how identities should be addressed inside a sandbox
3. what exact durable objects and APIs `Memory` should expose first
4. how `Impulse` jobs are defined, scheduled, and safety-limited
5. what exact auth/token mechanism should enforce trust between `Nerve`, `Brain`, and the system-space services
6. how `Introspect` is authorized to inspect and mutate live state
7. what minimal cross-service contract format should be standardized early

## Status

This document is a living overview capturing high-level architecture discussion.
It should be updated as Hydrai's contracts become more concrete.
