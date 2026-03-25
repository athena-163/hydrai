"""CLI for Toolbox."""

from __future__ import annotations

import argparse
import logging
import signal

from hydrai_toolbox.auth import InternalAuthGate
from hydrai_toolbox.config import load_config
from hydrai_toolbox.gmail_auth import bootstrap_gmail_oauth
from hydrai_toolbox.service import ToolboxService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Hydrai Toolbox service.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "gmail-auth"])
    parser.add_argument("--config", required=True, help="Absolute path to Toolbox.json")
    parser.add_argument("--log-level", default="INFO", help="Python log level")
    parser.add_argument("--backend-ref", default="", help="gmail_oauth backend reference for gmail-auth")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    command = args.command or "serve"
    if command == "gmail-auth":
        config = load_config(args.config)
        backend = config.email.gmail_oauth.get(args.backend_ref)
        if backend is None:
            raise SystemExit(f"unknown gmail_oauth backend_ref: {args.backend_ref}")
        token_path = bootstrap_gmail_oauth(backend)
        print(token_path)
        return 0

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))
    config = load_config(args.config)
    auth_gate = InternalAuthGate.from_env()
    service = ToolboxService(config, auth_gate)
    service.start()
    def _shutdown(_signum, _frame):
        service.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        service.wait()
    finally:
        service.stop()
    return 0
