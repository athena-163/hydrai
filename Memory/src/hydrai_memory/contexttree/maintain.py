"""Thread-based maintenance helpers for Hydrai ContexTree."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .core import ContexTree


@dataclass
class MaintenanceHandle:
    tree: ContexTree
    interval: float

    def start(self) -> None:
        self.tree.start_maintenance(interval=self.interval)

    def stop(self, timeout: float = 10) -> None:
        self.tree.stop_maintenance(timeout=timeout)

    def status(self) -> dict:
        return self.tree.maintenance_status()


def start_registered_maintenance(tree: ContexTree, interval: float = 300) -> MaintenanceHandle:
    handle = MaintenanceHandle(tree=tree, interval=interval)
    handle.start()
    return handle
