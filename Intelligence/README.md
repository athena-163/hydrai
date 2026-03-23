# Hydrai Intelligence

`Intelligence` is Hydrai's model-serving middleware.

It runs in system space and exposes configured AI model routes through a
uniform internal HTTP API.

## Scope

Current supported route families:

1. remote chat/generation routes
2. local `llama-server`-backed chat routes
3. local embedding routes

Current route endpoints:

1. `POST /v1/chat/completions`
2. `POST /v1/embeddings`
3. `GET /health`

## Install

From the `Intelligence/` directory:

```bash
python3 -m pip install .
```

Editable install for development:

```bash
python3 -m pip install -e .
```

Installed console entrypoint:

```bash
hydrai-intelligence --config /abs/path/config.json
```

Source entrypoint:

```bash
PYTHONPATH=src python3 -m intelligence --config /abs/path/config.json
```

## Runtime Inputs

Required:

1. `--config /abs/path/config.json`

Security mode:

1. `HYDRAI_SECURITY_MODE=dev`
2. `HYDRAI_SECURITY_MODE=secure`

Internal auth in `secure` mode:

1. `HYDRAI_INTERNAL_TOKENS_JSON`
2. or compatibility fallback: `HYDRAI_INTERNAL_TOKEN_ID` + `HYDRAI_INTERNAL_TOKEN`

Provider keys:

1. `XAI_API_KEY`
2. `ALIBABA_API_KEY`

## Example Config

See [config.example.json](/Users/zeus/Codebase/hydrai/Intelligence/Configs/config.example.json).

That example currently reflects the real route inventory on this machine:

1. `qwen3.5-plus`
2. `grok-4.20-0309-reasoning`
3. `grok-4-1-fast-reasoning`
4. local `qwen3-32b-vl`
5. local `qwen3-4b`
6. `BAAI/bge-m3`

## Verified Capability Notes

Based on live testing:

1. `qwen3.5-plus`: text, image, and video work
2. `grok-4.20-0309-reasoning`: text, image, and search work; direct video input should be treated as unsupported
3. `grok-4-1-fast-reasoning`: text, image, and search work; direct video input should be treated as unsupported
4. local `qwen3-32b-vl`: text and image work
5. local `qwen3-4b`: text works
6. `bge-m3`: returns base64 embeddings with dimension `1024`

## Test

```bash
python3 -m compileall src/intelligence
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

## Service Templates

Example service-manager units are included for:

1. macOS `launchd`: [com.hydrai.intelligence.plist.example](/Users/zeus/Codebase/hydrai/Intelligence/Deploy/launchd/com.hydrai.intelligence.plist.example)
2. Linux `systemd`: [hydrai-intelligence.service.example](/Users/zeus/Codebase/hydrai/Intelligence/Deploy/systemd/hydrai-intelligence.service.example)

Those templates are examples only. Adjust paths, user, env vars, and config
path for the target machine.

## References

1. [OVERVIEW.md](/Users/zeus/Codebase/hydrai/Intelligence/OVERVIEW.md)
2. [SPEC.md](/Users/zeus/Codebase/hydrai/Intelligence/SPEC.md)
3. [TRUST.md](/Users/zeus/Codebase/hydrai/TRUST.md)
