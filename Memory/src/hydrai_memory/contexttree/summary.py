""".SUMMARY.json read/write/merge logic (v2 format)."""

import json
import logging
import os

logger = logging.getLogger(__name__)

SUMMARY_FILENAME = ".SUMMARY.json"


def _empty_summary() -> dict:
    return {"summary": "", "vec": "", "manual": False, "files": {}}


def _migrate_v1(v1_data: dict) -> dict:
    """Convert v1 .SUMMARY.json format to v2 in-memory.

    v1 format: {summary, summary_manual, text: [{name: summary}, ...],
                binary: [{name: summary}, ...], folders: [...]}
    v2 format: {summary, vec, manual, files: {name: {text, vec}, ...}}
    """
    result = _empty_summary()
    result["summary"] = v1_data.get("summary", "")
    result["manual"] = bool(v1_data.get("summary_manual", False))
    for key in ("text", "binary"):
        entries = v1_data.get(key, [])
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    for filename, summary_text in entry.items():
                        result["files"][filename] = {
                            "text": summary_text if isinstance(summary_text, str) else "",
                            "vec": "",
                        }
    return result


def _is_v1_format(data: dict) -> bool:
    """Detect v1 format by presence of 'text' key as a list."""
    return isinstance(data.get("text"), list)


def load_summary(folder_path: str) -> dict:
    """Load .SUMMARY.json from folder_path.

    Detects v1 format and migrates transparently.
    Returns an empty structure if the file doesn't exist or is malformed.
    """
    path = os.path.join(folder_path, SUMMARY_FILENAME)
    if not os.path.isfile(path):
        return _empty_summary()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Not a dict")
        if _is_v1_format(data):
            return _migrate_v1(data)
        # Parse v2 format
        result = _empty_summary()
        if isinstance(data.get("summary"), str):
            result["summary"] = data["summary"]
        if isinstance(data.get("vec"), str):
            result["vec"] = data["vec"]
        result["manual"] = bool(data.get("manual", False))
        files = data.get("files", {})
        if isinstance(files, dict):
            for filename, entry in files.items():
                if isinstance(entry, dict):
                    result["files"][filename] = {
                        "text": entry.get("text", "") if isinstance(entry.get("text"), str) else "",
                        "vec": entry.get("vec", "") if isinstance(entry.get("vec"), str) else "",
                    }
        return result
    except Exception as e:
        logger.warning("Malformed %s in %s: %s", SUMMARY_FILENAME, folder_path, e)
        return _empty_summary()


def save_summary(folder_path: str, data: dict) -> None:
    """Write .SUMMARY.json atomically (write .tmp then os.rename)."""
    path = os.path.join(folder_path, SUMMARY_FILENAME)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.rename(tmp_path, path)


def get_summary_mtime(folder_path: str) -> float:
    """Return the mtime of .SUMMARY.json, or 0.0 if it doesn't exist."""
    path = os.path.join(folder_path, SUMMARY_FILENAME)
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def prune_entries(data: dict, existing_files: set[str]) -> dict:
    """Remove entries from files dict for filenames no longer on disk."""
    data["files"] = {
        name: entry for name, entry in data["files"].items()
        if name in existing_files
    }
    return data


def merge_entries(data: dict, discovered_files: set[str]) -> dict:
    """Add newly discovered files with empty text/vec."""
    for name in sorted(discovered_files):
        if name not in data["files"]:
            data["files"][name] = {"text": "", "vec": ""}
    return data


def get_file_summary(data: dict, filename: str) -> str:
    """Look up a file's summary text. Returns '' if not found."""
    entry = data["files"].get(filename)
    if entry and isinstance(entry, dict):
        return entry.get("text", "")
    return ""


def set_file_summary(data: dict, filename: str, text: str, vec: str = "") -> dict:
    """Set or update a file's summary text and optional vector."""
    if filename in data["files"]:
        data["files"][filename]["text"] = text
        if vec:
            data["files"][filename]["vec"] = vec
    else:
        data["files"][filename] = {"text": text, "vec": vec}
    return data


def remove_file_entry(data: dict, filename: str) -> dict:
    """Remove a file entry from the files dict."""
    data["files"].pop(filename, None)
    return data


def rename_file_entry(data: dict, old_name: str, new_name: str) -> dict:
    """Rename a file entry, preserving its summary and vector."""
    if old_name in data["files"]:
        data["files"][new_name] = data["files"].pop(old_name)
    return data
