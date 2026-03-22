# Intelligence Overview

`Intelligence` is the Hydrai service responsible for exposing actual AI model
capabilities behind clean internal HTTP interfaces.

It is the model-facing middleware layer of Hydrai:

1. sandbox `Brain` instances do not talk to model vendors or local model runtimes directly
2. `Intelligence` owns model-route configuration and model-provider adaptation
3. credentials and model-runtime details remain in system space

## Role In Hydrai

`Intelligence` runs in system space.

Its job is to make model access:

1. config-driven
2. stateless
3. parallel by default
4. isolated from sandbox execution

At the architectural level, it is comparable to the model-serving portion of
`aios/Proxy`, but it should be built fresh as a clean standalone package with a
narrower and clearer responsibility.

## Packaging Rule

Like the other Hydrai modules, `Intelligence` should be:

1. an independent service
2. a complete Python package that can be installed on its own
3. deployable without depending on shared internal Hydrai libraries
4. defined by explicit HTTP and config contracts rather than cross-module code reuse

This service-boundary rule is intentional. The goal is to let Hydrai evolve one
service at a time without repeated cross-service rewrites.

## Core Responsibility

`Intelligence` serves as middleware to real AI models declared in config files.

It should:

1. read model-route definitions from configuration
2. expose each configured model on its own local port
3. translate a stable internal API into provider-specific or runtime-specific behavior
4. keep zero durable state
5. maximize safe parallel handling across routes

`Intelligence` is not the owner of durable model metadata beyond its loaded
runtime configuration, and it is not the owner of workflow/session state.

## Model Categories

The service must support multiple model classes under one clean routing model.

### 1. Remote LLM Models

Examples currently discussed:

1. `qwen3.5-plus` from Alibaba
2. `grok-4.1-fast-reasoning` from xAI
3. `grok-4.2-beta` from xAI

High-level rules:

1. API keys come from environment variables in system space
2. the same provider key may back multiple configured model routes
3. different models should still map to different local ports
4. provider-specific details must stay inside `Intelligence`

Current environment check confirms the expected system-space env vars exist for:

1. `XAI_API_KEY`
2. `ALIBABA_API_KEY`

### 2. Local LLM Models

Examples currently discussed:

1. local Qwen3 32B VL
2. local Qwen3 4B

High-level rules:

1. local model routes are also config-driven
2. `Intelligence` should integrate local `llama-server` style serving internally instead of relying on a separately managed external runtime
3. config should describe the local model artifact location and runtime limits
4. local routes should still present the same stable internal API shape as remote routes where practical

Likely config concerns, to be detailed later in `SPEC.md`:

1. model file location
2. context window limit
3. GPU/offload/runtime knobs
4. concurrency limits
5. startup policy and health behavior

### 3. Embedding Models

Current target:

1. BGE-M3 style embedding support, to be verified precisely during implementation

High-level rules:

1. embedding routes belong in `Intelligence`
2. text input should be converted to a 1024-dimensional vector
3. the vector should be returned in base64 form
4. embeddings should be exposed through an internal HTTP endpoint just like other model capabilities

The exact installed model name and runtime path should be confirmed during the
implementation phase rather than hardcoded here.

### 4. Future AI Model Types

`Intelligence` should be designed to grow beyond text generation.

Future examples may include:

1. image generation
2. multimodal generation
3. other specialized AI inference routes

The service should therefore define route types cleanly instead of assuming
every configured endpoint is a chat-completions model.

## Port Model

Each model route gets its own configurable port.

Current preference:

1. use the `61xxx` range for `Intelligence` service ports
2. keep port assignments explicit in config
3. allow multiple routes from the same vendor with different ports and model mappings

Example intent:

1. one port for xAI Grok 4.1 fast reasoning
2. another port for xAI Grok 4.2 beta
3. separate ports for local Qwen routes
4. separate ports for embedding routes where appropriate

## API Direction

The detailed API contract belongs in `SPEC.md`, but the high-level direction is:

1. callers should see a stable internal HTTP surface
2. `Intelligence` should adapt that surface to each provider or local runtime
3. route behavior should be config-selected rather than hardcoded
4. local and remote models should feel uniform to trusted internal callers wherever reasonable

This means the service should expose an internal model-facing API, not just a
thin raw TCP forwarder.

## Statelessness And Parallelism

`Intelligence` should hold zero durable state.

Operationally, it may hold only the minimum runtime state needed to serve:

1. loaded config
2. active route bindings
3. in-memory provider/runtime clients
4. in-flight request accounting
5. temporary process-local caches required for performance

Concurrency direction:

1. maximize parallel request handling across routes
2. treat each route independently
3. allow route-specific concurrency limits when needed
4. give special care to local-model routes, since they are real compute bottlenecks

## Trust Boundary

`Intelligence` lives in trusted system space.

Within the Hydrai trust model:

1. system-space services are trusted
2. sandbox space is lower-trust
3. sandbox access to model capabilities should be mediated through the sandbox's associated `Brain`
4. access from sandbox to system-space services must be explicitly authenticated

Working access rule for `Intelligence`:

1. it should accept requests only from trusted internal callers under the Hydrai service-auth scheme
2. it should not expose privileged model access to arbitrary sandbox processes
3. provider credentials must never be visible inside sandbox space

At the current high level, the exact token/auth handshake is still deferred to
later design work, but `Intelligence` must be built assuming authenticated
internal-only usage.

## Configuration Direction

Configuration is central to this service.

At a high level, config should define:

1. route type
2. listen port
3. backing provider or local runtime kind
4. model identifier or local model artifact
5. env var names for credentials where needed
6. route-specific extra parameters
7. route-specific limits and capabilities

The important architectural point is that model inventory belongs in config,
not in code.

## Relationship To Other Services

`Intelligence` should remain narrow.

It should not absorb responsibilities belonging to:

1. `Toolbox` for non-model external tools
2. `Memory` for durable state
3. `Nerve` for session routing
4. `Brain` for execution logic
5. `Peripheral` for human-channel integration

`Intelligence` exists to make real model capabilities available through clean,
trusted, config-defined routes. Nothing more.

## Current Design Considerations

These points should shape the later detailed spec:

1. keep the package standalone and installable
2. keep the route model generic enough for remote, local, embedding, and future inference types
3. keep local-model serving inside `Intelligence` when that reduces external operational sprawl
4. keep request authentication mandatory in secure deployment
5. keep one-port-per-route for clarity and operational control
6. keep provider/model/runtime specifics behind configuration and adapters
7. keep the service stateless except for runtime-only process state

## Deferred To `SPEC.md`

The following are intentionally not fixed here yet:

1. exact config schema
2. exact HTTP endpoints
3. exact request/response translation rules
4. exact local `llama-server` lifecycle model
5. exact embedding endpoint shape
6. exact auth headers and token-validation flow
7. exact concurrency and overload behavior

This file captures the top-level requirements and design constraints only.
