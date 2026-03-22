"""CLI entrypoint."""

from __future__ import annotations

import argparse
import logging
import signal

from .auth import AuthError, InternalAuthGate
from .config import ConfigError, load_config
from .server import IntelligenceService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hydrai Intelligence service")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    try:
        config = load_config(args.config)
        auth_gate = InternalAuthGate.from_env()
    except (ConfigError, AuthError) as exc:
        logging.error("%s", exc)
        return 2

    service = IntelligenceService(config, auth_gate)
    stopped = False

    def _stop(*_args):
        nonlocal stopped
        if not stopped:
            stopped = True
            service.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        service.start()
        service.wait()
    except KeyboardInterrupt:
        _stop()
    except Exception:
        _stop()
        raise
    return 0

