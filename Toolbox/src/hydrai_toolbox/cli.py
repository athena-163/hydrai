"""CLI for Toolbox."""

from __future__ import annotations

import argparse
import logging
import signal

from hydrai_toolbox.auth import InternalAuthGate
from hydrai_toolbox.config import load_config
from hydrai_toolbox.service import ToolboxService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Hydrai Toolbox service.")
    parser.add_argument("--config", required=True, help="Absolute path to Toolbox.json")
    parser.add_argument("--log-level", default="INFO", help="Python log level")
    return parser


def main() -> int:
    args = build_parser().parse_args()
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
