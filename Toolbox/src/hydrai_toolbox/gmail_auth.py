"""Gmail OAuth bootstrap helpers."""

from __future__ import annotations

import os

from hydrai_toolbox.config import GmailOAuthBackendConfig


def bootstrap_gmail_oauth(backend: GmailOAuthBackendConfig) -> str:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("gmail_oauth dependencies are not installed") from exc
    os.makedirs(os.path.dirname(backend.token_path), exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(backend.credentials_path, list(backend.scopes))
    creds = flow.run_local_server(port=0)
    with open(backend.token_path, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    return backend.token_path
