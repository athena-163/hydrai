# Hydrai Brain Overview

`Brain` is Hydrai's sandbox-space cognition and execution runtime.

It is the one service that lives inside each sandbox and acts as the execution
surface for that sandbox's identities and sessions.

Hydrai should keep most of the strong AIOS Brain model, while trimming it into a
leaner sandbox-local runtime that depends on system-space services for durable
state, models, and credentialed tools.

## 1. Role In Hydrai

`Brain` should:

1. run inside one sandbox as that sandbox's cognition runtime
2. execute requests for identities and sessions in that sandbox only
3. stay stateless across requests
4. read durable state through `Memory`
5. use models through `Intelligence`
6. use credentialed external tools through `Toolbox`
7. accept inbound requests only from `Nerve`

`Brain` should not:

1. own durable state
2. hold provider credentials
3. hold mailbox or search credentials
4. bypass `Memory`, `Intelligence`, or `Toolbox`
5. reach across sandboxes

## 2. Deployment Shape

Hydrai runs:

1. one `Brain` instance per sandbox
2. one sandbox per Unix user

So each `Brain`:

1. runs as the sandbox user
2. sees only that sandbox's user-space world directly
3. may damage its own sandbox
4. must not be able to damage system space or other sandboxes

This makes `Brain` the bounded risky executor, while system-space services own
trust, credentials, and durable truth.

## 3. Core Execution Model

Hydrai should keep the AIOS Brain execution shape:

1. deterministic bootstrap
2. root execution node
3. tool loop
4. optional child-node spawning

Meaning:

1. a request arrives from `Nerve`
2. `Brain` bootstraps the minimum bounded starting state
3. a root node runs on one chosen model/worker
4. that node may answer directly, call tools, or spawn child work
5. runtime stops when a bounded result is produced

This is the right shape because it keeps cognition explicit and bounded instead
of collapsing into hidden routing logic.

## 4. Bootstrap

Bootstrap should stay deterministic and non-cognitive.

Responsibilities:

1. normalize the inbound request
2. gather relevant identity, session, and resource state from `Memory`
3. prepare readable and writable scope
4. prepare visible skills and worker/model options
5. provide a bounded starting state to the root node

Bootstrap should not:

1. think
2. silently select hidden sub-workers
3. make durable mutations on its own

In Hydrai terms, bootstrap should primarily depend on:

1. `Memory` for identity, session, resource, and skill state
2. local request/session context from `Nerve`

## 5. Query Nodes

The main runtime unit should remain a node-like execution unit.

A node should receive:

1. one local task
2. bounded context
3. visible tools
4. visible skills
5. visible worker/model choices
6. recursion and turn limits

A node may:

1. answer directly
2. call tools
3. spawn child work
4. return bounded failure or uncertainty

Root node and child node should stay the same kind of execution unit.

## 6. Nested And Tree Execution

Hydrai should keep nested or tree-shaped LLM execution.

That means a node may spawn a child node to:

1. delegate a focused sub-task
2. use a different model or worker
3. perform a bounded side investigation
4. call a native external agent such as Claude or Codex

Important rule:

1. child spawning must stay explicit
2. runtime should not hide delegation decisions in bootstrap

This preserves the AIOS idea that the node chooses child work directly, rather
than the system silently routing requests behind the model's back.

## 7. Tool Loop

Hydrai should keep the explicit tool loop.

The node must be able to:

1. inspect available tools
2. call them one at a time
3. observe structured results
4. continue or stop

The major Hydrai difference is the backend split:

1. `Memory` provides state and storage tools
2. `Toolbox` provides external credentialed tools
3. `Intelligence` provides model routes

`Brain` should not directly own those integrations. It should orchestrate them.

## 8. Skills

Hydrai should keep the AIOS principle:

1. tools are the executable surface
2. skills are the discovery and guidance surface

So `Brain` should:

1. wrap tool ability in a skill-oriented prompt surface
2. let the model discover capability through skills
3. still keep a real executable tool catalog underneath

This fits Hydrai well because:

1. `Memory` already owns `SkillSet`
2. identities and sandboxes may constrain visible skills
3. execution remains tool-driven even when the prompt is skill-first

## 9. Model Selection

Hydrai should keep model selection as explicit and constrained.

At high level:

1. the runtime has a visible worker/model catalog
2. the root node starts from an effective default
3. child work may choose another model within visible limits
4. runtime should not silently pick arbitrary replacements

The actual selection logic will later depend on:

1. request type
2. sandbox/session restrictions
3. model restraints and capabilities
4. cost/speed/tolerance policies

But the big rule should remain:

1. model choice is explicit and bounded, not magical

## 10. Native Identities

Hydrai must support native identities such as:

1. Claude
2. Codex
3. other third-party agent systems

At the top level, `Brain` should treat these as first-class execution targets.

That means:

1. native identities can participate in sessions like other identities
2. `Brain` may call them through dedicated native APIs
3. their persona comes from `Memory`
4. their private internal state remains external to Hydrai

So Hydrai Brain should support both:

1. model-backed local cognition
2. native delegate execution

## 11. Text-First Multimodal

Hydrai should remain text-first while supporting multimodal input and output.

Meaning:

1. text is still the backbone of request, reasoning, and response
2. images and other media may be part of the request context
3. multimodal model routes may be used when needed
4. result transport should still stay primarily text-oriented

This keeps the runtime simple while still allowing:

1. image understanding
2. later richer multimodal behavior

## 12. Concurrency

Hydrai should keep the AIOS concurrency rule:

1. parallel across sessions
2. serialized within one session

This remains the cleanest rule because:

1. it avoids same-session mutation races
2. it allows broad sandbox throughput
3. it matches the trust and state model already used elsewhere in Hydrai

Since there is one `Brain` per sandbox, this means:

1. the sandbox `Brain` may process many sessions concurrently
2. one session lane should remain ordered

## 13. Hydrai-Specific Simplifications

Compared with AIOS Brain, Hydrai Brain should become leaner.

The main simplifications are:

1. no durable state ownership
2. no model proxy ownership
3. no external-tool credential ownership
4. cleaner separation from routing and trust control

So the practical architecture becomes:

1. `Nerve` routes
2. `Brain` executes
3. `Memory` remembers
4. `Intelligence` thinks at the model layer
5. `Toolbox` reaches the outside world

## 14. Current Big-Picture Contract

At high level, Hydrai `Brain` is:

1. one sandbox-local stateless execution service
2. driven by deterministic bootstrap
3. centered on a node-based tool loop
4. capable of nested/tree execution
5. model-constrained rather than magically routed
6. text-first with multimodal support
7. able to use native identities like Claude and Codex

This overview intentionally stops short of:

1. request schema detail
2. exact tool catalog
3. exact model-selection algorithm
4. exact native identity protocol
5. prompt template design

Those belong in `SPEC.md`.
