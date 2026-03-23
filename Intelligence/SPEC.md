# Intelligence Specification

`Intelligence` is Hydrai's model-serving middleware. It runs in system space
and exposes configured AI model routes through a uniform internal HTTP API.

This spec defines the first intended contract for the service. It is grounded
in Hydrai's top-level [overview](/Users/zeus/Codebase/hydrai/OVERVIEW.md),
[trust model](/Users/zeus/Codebase/hydrai/TRUST.md), and the useful route ideas
from `aios/Proxy`, but it is a fresh service design.

## 1. Goals

`Intelligence` must:

1. be an independent installable Python package and service
2. serve remote and local AI model routes from config
3. expose one configured route per local port
4. present a uniform internal API to trusted callers
5. keep provider keys and local-runtime details in system space
6. keep zero durable state
7. support high parallelism, with route-specific concurrency limits where needed

`Intelligence` must not:

1. own session state
2. own durable model registry state outside runtime config
3. own external non-model tool integrations
4. assume all routes support the same features

## 2. Runtime Position

Hydrai trust position:

1. `Intelligence` runs in trusted system space
2. callers are trusted internal services only
3. sandbox code must never see provider API keys
4. the service must follow the Hydrai runtime token scheme from [TRUST.md](/Users/zeus/Codebase/hydrai/TRUST.md)

Default access expectation:

1. sandbox-origin access reaches `Intelligence` only through the sandbox's `Brain`
2. in secure deployments, protected endpoints require internal auth
3. in explicit development bring-up mode, auth checks may be bypassed

## 3. Service Shape

`Intelligence` is a single logical service that may host many active model
routes at once.

High-level runtime model:

1. one process loads route config
2. one local HTTP listener is bound per configured route port
3. each route is backed by one adapter/runtime definition
4. all routes share the same service binary but remain operationally separate

This keeps deployment simple while preserving one-port-per-route clarity.

### 3.1 Startup Contract

`Intelligence` should receive its config file path at startup.

Initial direction:

1. config path is an explicit startup argument
2. the service should not hardcode one machine-specific config location
3. the repo may keep an example config file for reference

Likely CLI shape:

1. `python -m intelligence --config /abs/path/config.json`
2. an installed console script equivalent is also acceptable later

## 4. Supported Route Classes

The route model must support at least these route classes.

### 4.1 Remote Chat / Generation Routes

Examples:

1. Alibaba `qwen3.5-plus`
2. xAI `grok-4.1-fast-reasoning`
3. xAI `grok-4.2-beta`

Properties:

1. upstream target is remote HTTP API
2. API key is resolved from a system-space env var
3. multiple routes may share the same env var while mapping to different models and ports
4. provider-specific request/response translation stays inside route adapters

### 4.2 Local Chat / Generation Routes

Examples:

1. local Qwen3 32B VL
2. local Qwen3 4B

Properties:

1. backing runtime is local to the system-space host
2. route config defines model artifact and runtime limits
3. local runtime management belongs inside `Intelligence`
4. local routes should expose the same caller-facing API shape as remote routes where practical

Initial direction:

1. local LLM hosting should integrate `llama-server`-style runtime management within `Intelligence`
2. exact process model is deferred, but `Intelligence` owns the lifecycle

### 4.3 Embedding Routes

Initial direction:

1. embedding belongs inside `Intelligence`
2. input is text
3. output is a base64-encoded vector
4. initial target vector dimension is expected to be 1024

The exact model name and runtime implementation should be confirmed during implementation.

### 4.4 Future Inference Routes

The route system should allow future expansion such as:

1. image generation
2. multimodal generation
3. additional specialized inference types

Therefore route config must declare route type explicitly instead of assuming
all routes are chat models.

## 5. Port Model

Each configured route listens on its own local port.

Current convention:

1. `Intelligence` ports should use the `61xxx` range
2. port assignment is explicit in config
3. each route is independently bindable, health-checkable, and limitable

Examples:

1. one xAI model per port
2. one Alibaba model per port
3. one local Qwen model per port
4. one embedding route per port if desired

## 6. Uniform API Surface

The caller-facing API should be OpenAI-style and uniform across route types as
far as possible.

The point is not to mimic vendors perfectly. The point is to give trusted
Hydrai callers one stable internal contract.

### 6.1 Chat / Generation Endpoint

Primary route endpoint:

1. `POST /v1/chat/completions`

Intent:

1. use an OpenAI-style chat-completions request format
2. support multimodal content blocks in the request shape
3. support optional `think` hints
4. support optional server-side search hints
5. let adapters degrade or reject unsupported features per route capability

### 6.2 Embedding Endpoint

Embedding routes should expose:

1. `POST /v1/embeddings`

Intent:

1. use a standard embedding-style request surface
2. accept text input
3. return a base64 vector payload rather than a raw float array

This differs slightly from typical OpenAI output shape, but it is still better
to keep embeddings under a recognizable `/v1/embeddings` API family than to
invent an unrelated internal path.

### 6.3 Health Endpoint

Each route should expose:

1. `GET /health`

Intent:

1. return route metadata and runtime status
2. expose enough information for `Nerve` and `Introspect`
3. avoid leaking secrets

## 7. Request Shape

### 7.1 Chat Request

The baseline request shape should follow the OpenAI chat-completions style:

1. `model`
2. `messages`
3. optional generation controls
4. optional route-supported feature hints

Route config may override the upstream physical model identifier. Callers
should not need to know vendor-specific model strings.

Multimodal direction:

1. `messages[].content` may be a string or structured content array
2. structured content should allow text plus modality blocks such as image, video, document, and audio references
3. adapters decide how to translate or degrade those blocks for the actual route

### 7.2 Think Hint

Thinking should be explicit in the API surface rather than hidden as a
provider quirk.

Initial direction:

1. support a caller-provided `think` field on chat requests
2. `think` is a level, not a boolean
3. expected levels are `off`, `low`, `mid`, and `high`
4. routes may honor, map, cap, or reject the requested level

This keeps the caller contract route-agnostic while still allowing
model-specific behavior underneath.

### 7.3 Server-Side Search Hint

Search should be explicit in the request contract.

This is a deliberate departure from `aios/Proxy`, where xAI web search was
implicitly activated inside one provider adapter when reasoning effort was high.

Initial direction:

1. callers may request server-side search explicitly in the chat endpoint
2. routes that support server-side search may enable it
3. routes that do not support it must reject or ignore it clearly
4. search is a route capability, not an xAI-only hidden behavior

This keeps the API honest and general.

### 7.4 Embedding Request

Embedding requests should accept:

1. model hint or route-local logical model name
2. one text input or a small batch if batching is later allowed

Initial output direction:

1. return base64 vector data
2. include model metadata
3. include dimension metadata if helpful

## 8. Capability Model

Not every route supports every feature.

Each route definition should declare capability hints such as:

1. structured content input
2. image input with size limit
3. video input with size limit
4. inline audio input with size limit
5. document input with size limit
6. server-side search
7. supported `think` levels
8. embedding support

Behavioral rule:

1. the public route API is uniform
2. real feature support is determined by route capability
3. adapters must translate, degrade, or reject based on that capability

This lets `Brain` talk to a stable API while still respecting model reality.

## 9. Route Configuration

Detailed schema can still evolve, but the config model should include:

1. route type
2. listen port
3. provider/runtime adapter
4. upstream target or local runtime definition
5. logical route name
6. physical model identifier if needed
7. credential env var name if needed
8. supported `think` levels
9. modality size limits
10. search support
11. context window limit
12. extra provider params
13. capability flags
14. concurrency settings
15. timeout settings

Local-model routes should additionally allow runtime-oriented fields such as:

1. model artifact path
2. startup policy

Important rule:

1. model inventory belongs in config, not in service code

### 9.1 Proposed V1 Config Shape

The current preferred config direction is a single route list with explicit
`type` and simple adapter names.

Example:

```json
{
  "routes": [
    {
      "name": "grok41",
      "type": "chat",
      "adapter": "remote",
      "listen": 6101,
      "target": "https://api.x.ai",
      "model": "grok-4.1-fast-reasoning",
      "key_env": "XAI_API_KEY",
      "think": ["off", "low", "mid", "high"],
      "modalities": {
        "image_kb": 0,
        "video_kb": 0
      },
      "search": true,
      "context_k": 128,
      "limits": {
        "max_concurrency": 8,
        "timeout_sec": 120
      },
      "extra_params": {}
    },
    {
      "name": "qwen4b",
      "type": "chat",
      "adapter": "llama",
      "listen": 6111,
      "model": "qwen3-4b",
      "artifact": "/abs/path/model.gguf",
      "think": ["off", "low", "mid"],
      "modalities": {
        "image_kb": 0,
        "video_kb": 0
      },
      "search": false,
      "context_k": 64,
      "limits": {
        "max_concurrency": 1,
        "timeout_sec": 300
      }
    },
    {
      "name": "bge-m3",
      "type": "embedding",
      "adapter": "embedding",
      "listen": 6121,
      "model": "BAAI/bge-m3",
      "output_dimension": 1024,
      "output_encoding": "base64",
      "limits": {
        "max_concurrency": 4,
        "timeout_sec": 60
      }
    }
  ]
}
```

Field intent:

1. `type`: caller-visible API family such as `chat` or `embedding`
2. `adapter`: implementation family such as `remote`, `llama`, or `embedding`
3. `think`: supported `think` levels for the route
4. `modalities`: per-modality size limits in KB, where `0` means unsupported
5. `search`: whether server-side search is supported
6. `context_k`: context window in thousands of tokens
7. `limits.max_concurrency`: maximum active in-flight requests for the route

### 9.2 Current Device Inventory

The current machine is expected to support at least these initial routes:

1. remote `qwen3.5-plus` via API, with image and video support
2. remote `grok-4.20-0309-reasoning` via API, with image support and no direct video input
3. remote `grok-4.1-fast-reasoning` via API, with image support and no video
4. local `qwen3-32b-vl` via llama, with 64K context and image support but no video
5. local `qwen3-4b` via llama, intended for content summarization
6. local `bge-m3` embedding

These should be reflected in the example config kept in the repo.

## 10. Adapters

`Intelligence` should use explicit adapter types instead of mixing all logic
into the HTTP handler.

Likely adapter families:

1. `remote`
2. `llama`
3. `embedding`
4. future specialized adapters such as image-generation

Each adapter is responsible for:

1. validating route-specific config
2. mapping the uniform internal request into the real provider/runtime request
3. mapping the provider/runtime response back into the uniform response shape
4. enforcing capability-aware behavior

## 11. Auth And Trust Handling

The auth scheme must follow [TRUST.md](/Users/zeus/Codebase/hydrai/TRUST.md).

Initial rules:

1. in `secure` mode, protected route endpoints require valid internal auth
2. in `dev` mode, internal auth may be bypassed for bring-up/testing
3. missing auth material in `secure` mode is a startup/config error
4. provider API keys must never be returned, logged, or exposed to sandbox callers

At this service boundary, `Intelligence` should treat all requests as internal
service requests, not end-user public API traffic.

## 12. Statelessness

`Intelligence` owns no durable state.

Allowed runtime-only state:

1. loaded route config
2. active route listeners
3. in-memory HTTP clients
4. local-runtime subprocess handles
5. local-model caches
6. in-flight request counters

No session, identity, or workflow state should live here.

## 13. Concurrency And Overload

Concurrency policy should be route-local.

Rules:

1. different routes may serve concurrently
2. each route may define its own `max_concurrency`
3. local-model routes should default to tighter limits than remote routes

Expected overload behavior:

1. if a route is saturated, return a clear overload response immediately
2. callers are responsible for retry/defer behavior
3. overload handling should be per route, not global to the whole service

Initial direction:

1. `Intelligence` should not keep an internal waiting queue in v1
2. route backpressure should be explicit to callers

## 14. Health And Observability

`GET /health` should expose per-route status without leaking secrets.

Useful fields:

1. route name
2. port
3. route type
4. adapter type
5. logical model name
6. capability flags
7. concurrency settings
8. current active request count
9. local-runtime readiness if applicable

`Intelligence` should also emit structured logs suitable for later integration
with `Introspect`.

## 15. Error Model

Caller-visible failures should be categorized clearly:

1. bad request shape
2. unsupported feature for this route
3. missing or invalid auth
4. route overload
5. upstream/provider failure
6. local runtime unavailable
7. config/runtime initialization failure

The service should favor explicit errors over silent hidden behavior when a
requested feature is unsupported.

## 16. Search Design Direction

Search support needs special attention.

Hydrai direction:

1. server-side search is an explicit caller-visible option
2. search support is declared by route capability
3. provider adapters may map that option into provider-native mechanisms
4. the route contract should not hide search behind unrelated reasoning settings

This is cleaner than the old `aios/Proxy` behavior where one provider adapter
implicitly turned on web search when reasoning was high.

The exact field name is still open, but the behavior principle is fixed.

## 17. Multimodal Design Direction

The uniform API should support multimodal requests even though not all routes do.

Route behavior options:

1. accept and forward natively
2. degrade to text references where reasonable
3. reject as unsupported

The important rule is that the request contract stays stable while route
capabilities determine actual support.

## 18. Initial Non-Goals

Not required for the first implementation:

1. public internet exposure
2. durable route registry state
3. cross-route model selection logic inside `Intelligence`
4. session-aware orchestration
5. non-model external tools
6. automatic fallback from one route to another

Those belong elsewhere or later.

## 19. Open Clarifications

The current design is coherent. The main remaining points worth clarifying
before implementation are:

1. the exact chat request fields for `think` and `search`
2. whether unsupported optional features should default to reject or ignore
3. whether `/v1/responses` should also be exposed internally, or only `/v1/chat/completions`
4. whether embeddings should support batching in v1
5. whether local model runtimes are started eagerly or lazily per route
6. whether one `Intelligence` process is enough initially or whether local-heavy routes should be splittable later

My current recommendation:

1. expose only `/v1/chat/completions`, `/v1/embeddings`, and `/health` in v1
2. make `search` and `think` explicit optional request fields
3. reject unsupported requested features clearly instead of silently ignoring them
4. keep embeddings single-input first
5. start with one process hosting many route listeners

## 20. Status

This spec defines the intended contract direction for `Intelligence`.
Implementation details may still evolve, but later design work should preserve
the service boundary, trust model, and uniform route API defined here.
