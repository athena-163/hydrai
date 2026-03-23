"""Vector search across .SUMMARY.json files in a ContexTree."""

import os

from .embedder import Embedder
from .summary import SUMMARY_FILENAME, load_summary


def search_vectors(
    root: str,
    query_vec,
    embedder: Embedder,
    top_k: int = 10,
    min_score: float = 0.3,
    paths: list[str] | None = None,
) -> dict:
    """Walk tree, load .SUMMARY.json files, score vectors against query.

    Returns::

        {
            "results": [{path, size, summary, score}, ...],
            "checked": int,   # entries with vectors that were scored
            "missing": int,   # entries without vectors (out-of-sync)
        }

    Up to *top_k* results sorted by cosine similarity descending.
    Only results with score >= min_score are included.
    Folder paths end with '/'. Files and folders are mixed by score.

    When *paths* is provided, only directories whose relative path starts
    with one of the given prefixes are searched (e.g. ``["memorables/",
    "dynamics/"]``).
    """
    root = os.path.realpath(root)
    # Normalize path prefixes for matching
    prefixes: list[str] | None = None
    if paths is not None:
        prefixes = [p.rstrip("/") for p in paths]
    results: list[dict] = []
    checked = 0
    missing = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d))
        )

        # Relative folder path from root
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            folder_path = ""
        else:
            folder_path = rel_dir.replace(os.sep, "/") + "/"

        # Path scope filter
        if prefixes is not None:
            rel_norm = rel_dir.replace(os.sep, "/")
            if rel_norm == ".":
                # Root itself — skip unless "" is in prefixes
                if "" not in prefixes:
                    continue
            elif not any(rel_norm == p or rel_norm.startswith(p + "/") for p in prefixes):
                continue

        summary_path = os.path.join(dirpath, SUMMARY_FILENAME)
        if not os.path.isfile(summary_path):
            continue

        data = load_summary(dirpath)

        # Score folder summary
        folder_vec_b64 = data.get("vec", "")
        if folder_vec_b64:
            checked += 1
            try:
                folder_vec = embedder.decode(folder_vec_b64)
                score = embedder.similarity(query_vec, folder_vec)
                if score >= min_score:
                    # Folder size = sum of direct children file sizes
                    folder_size = 0
                    for fn in os.listdir(dirpath):
                        fp = os.path.join(dirpath, fn)
                        if not fn.startswith(".") and os.path.isfile(fp) and not os.path.islink(fp):
                            try:
                                folder_size += os.path.getsize(fp)
                            except OSError:
                                pass
                    results.append({
                        "path": folder_path if folder_path else "/",
                        "size": folder_size,
                        "summary": data.get("summary", ""),
                        "score": round(score, 4),
                    })
            except Exception:
                pass
        else:
            missing += 1

        # Score file entries
        files = data.get("files", {})
        for filename, entry in files.items():
            if not isinstance(entry, dict):
                continue
            file_vec_b64 = entry.get("vec", "")
            if file_vec_b64:
                checked += 1
                try:
                    file_vec = embedder.decode(file_vec_b64)
                    score = embedder.similarity(query_vec, file_vec)
                    if score >= min_score:
                        file_abs = os.path.join(dirpath, filename)
                        try:
                            file_size = os.path.getsize(file_abs)
                        except OSError:
                            file_size = 0
                        results.append({
                            "path": folder_path + filename,
                            "size": file_size,
                            "summary": entry.get("text", ""),
                            "score": round(score, 4),
                        })
                except Exception:
                    pass
            else:
                missing += 1

    results.sort(key=lambda r: r["score"], reverse=True)
    return {"results": results[:top_k], "checked": checked, "missing": missing}
