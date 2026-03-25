# Hydrai Toolbox

`Toolbox` is Hydrai's external-tools bridge service.

It runs in system space and exposes normalized internal APIs for credentialed
tools such as web search and email.

Email backends currently supported:

1. `himalaya`
2. `imap_smtp`

`imap_smtp` is useful for providers like NetEase `163.com` that require an
IMAP `ID` payload before opening folders.

Startup:

```bash
hydrai-toolbox --config ~/Public/hydrai/Toolbox.json
```

Config:

- example: [`Configs/config.example.json`](/Users/zeus/Codebase/hydrai/Toolbox/Configs/config.example.json)

Endpoints:

1. `GET /health`
2. `GET /help`
3. `POST /web/search`
4. `POST /email/search`
5. `POST /email/read`
6. `POST /email/send`
7. `POST /email/draft`

Security:

1. `HYDRAI_SECURITY_MODE=dev` bypasses internal auth
2. `HYDRAI_SECURITY_MODE=secure` requires Hydrai internal tokens

The detailed architecture and contract live in:

1. [`OVERVIEW.md`](/Users/zeus/Codebase/hydrai/Toolbox/OVERVIEW.md)
2. [`SPEC.md`](/Users/zeus/Codebase/hydrai/Toolbox/SPEC.md)
