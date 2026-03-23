"""Path validation — traversal protection."""

import os


def validate_path(root: str, rel_path: str) -> str:
    """Resolve relative path and verify it stays within root.

    Returns the absolute resolved path.
    Raises ValueError("Path escapes root") if path escapes root.
    """
    resolved = os.path.realpath(os.path.join(root, rel_path))
    root_resolved = os.path.realpath(root)
    if not resolved.startswith(root_resolved + os.sep) and resolved != root_resolved:
        raise ValueError("Path escapes root")
    return resolved
