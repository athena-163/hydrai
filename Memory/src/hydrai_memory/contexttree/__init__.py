"""ContexTree - Directory-based context manager for AI applications."""

from .core import ContexTree
from .embedder import Embedder
from .maintain import MaintenanceHandle, start_registered_maintenance

__all__ = ["ContexTree", "Embedder", "MaintenanceHandle", "start_registered_maintenance"]
