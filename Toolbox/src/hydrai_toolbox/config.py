"""Config loading for Toolbox."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebSearchConfig:
    provider: str
    brave_key_env: str
    brave_timeout_sec: int


@dataclass(frozen=True)
class EmailGrant:
    sandbox_id: str
    identity_id: str
    mode: str


@dataclass(frozen=True)
class MailboxConfig:
    address: str
    backend: str
    backend_ref: str
    display_name: str
    grants: tuple[EmailGrant, ...]


@dataclass(frozen=True)
class HimalayaBackendConfig:
    bin_name: str
    timeout_sec: int


@dataclass(frozen=True)
class EmailConfig:
    mailboxes: tuple[MailboxConfig, ...]
    himalaya: HimalayaBackendConfig


@dataclass(frozen=True)
class ServiceConfig:
    config_path: str
    control_port: int
    web_search: WebSearchConfig
    email: EmailConfig


def _require_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > 65535:
        raise ValueError(f"{field_name} must be between 0 and 65535")
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def load_config(path: str) -> ServiceConfig:
    config_path = os.path.realpath(path)
    with open(config_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")

    control_port = _require_int(data.get("control_port"), "control_port")
    web_search = _load_web_search(data.get("web_search"))
    email = _load_email(data.get("email"))
    return ServiceConfig(
        config_path=config_path,
        control_port=control_port,
        web_search=web_search,
        email=email,
    )


def _load_web_search(raw: Any) -> WebSearchConfig:
    if not isinstance(raw, dict):
        raise ValueError("web_search must be an object")
    provider = _require_non_empty_string(raw.get("provider"), "web_search.provider")
    if provider != "brave":
        raise ValueError(f"unsupported web_search.provider: {provider}")
    brave = raw.get("brave")
    if not isinstance(brave, dict):
        raise ValueError("web_search.brave must be an object")
    return WebSearchConfig(
        provider=provider,
        brave_key_env=_require_non_empty_string(brave.get("key_env"), "web_search.brave.key_env"),
        brave_timeout_sec=_require_positive_int(brave.get("timeout_sec", 15), "web_search.brave.timeout_sec"),
    )


def _load_email(raw: Any) -> EmailConfig:
    if not isinstance(raw, dict):
        raise ValueError("email must be an object")
    raw_mailboxes = raw.get("mailboxes")
    if not isinstance(raw_mailboxes, list):
        raise ValueError("email.mailboxes must be a list")
    mailboxes: list[MailboxConfig] = []
    seen_addresses: set[str] = set()
    for item in raw_mailboxes:
        if not isinstance(item, dict):
            raise ValueError("email.mailboxes entries must be objects")
        address = _require_non_empty_string(item.get("address"), "email.mailboxes.address").lower()
        if address in seen_addresses:
            raise ValueError(f"duplicate mailbox address: {address}")
        backend = _require_non_empty_string(item.get("backend"), f"email.mailboxes[{address}].backend")
        if backend != "himalaya":
            raise ValueError(f"unsupported email backend: {backend}")
        backend_ref = _require_non_empty_string(item.get("backend_ref"), f"email.mailboxes[{address}].backend_ref")
        display_name = str(item.get("display_name") or "").strip()
        raw_grants = item.get("grants")
        if not isinstance(raw_grants, list) or not raw_grants:
            raise ValueError(f"email.mailboxes[{address}].grants must be a non-empty list")
        grants: list[EmailGrant] = []
        seen_grants: set[tuple[str, str]] = set()
        for grant in raw_grants:
            if not isinstance(grant, dict):
                raise ValueError(f"email.mailboxes[{address}].grants entries must be objects")
            sandbox_id = _require_non_empty_string(grant.get("sandbox_id"), "email.grant.sandbox_id")
            identity_id = _require_non_empty_string(grant.get("identity_id"), "email.grant.identity_id")
            mode = _require_non_empty_string(grant.get("mode"), "email.grant.mode").lower()
            if mode not in {"ro", "rw"}:
                raise ValueError("email.grant.mode must be 'ro' or 'rw'")
            key = (sandbox_id, identity_id)
            if key in seen_grants:
                raise ValueError(f"duplicate grant for {address}: {sandbox_id}/{identity_id}")
            grants.append(EmailGrant(sandbox_id=sandbox_id, identity_id=identity_id, mode=mode))
            seen_grants.add(key)
        mailboxes.append(
            MailboxConfig(
                address=address,
                backend=backend,
                backend_ref=backend_ref,
                display_name=display_name or address,
                grants=tuple(grants),
            )
        )
        seen_addresses.add(address)

    backends = raw.get("backends")
    if not isinstance(backends, dict):
        raise ValueError("email.backends must be an object")
    himalaya = backends.get("himalaya")
    if not isinstance(himalaya, dict):
        raise ValueError("email.backends.himalaya must be an object")
    return EmailConfig(
        mailboxes=tuple(mailboxes),
        himalaya=HimalayaBackendConfig(
            bin_name=_require_non_empty_string(himalaya.get("bin_name", "himalaya"), "email.backends.himalaya.bin_name"),
            timeout_sec=_require_positive_int(himalaya.get("timeout_sec", 60), "email.backends.himalaya.timeout_sec"),
        ),
    )
