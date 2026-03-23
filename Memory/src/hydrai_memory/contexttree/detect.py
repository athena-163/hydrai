"""Text vs binary detection and MIME type helpers."""

import logging
import mimetypes
import unicodedata

try:
    from charset_normalizer import from_bytes
except Exception:  # pragma: no cover - optional dependency fallback
    from_bytes = None

logger = logging.getLogger(__name__)

_FALLBACK_ENCODINGS = (
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
    "gb18030",
    "gbk",
    "big5",
    "shift_jis",
)


class _SimpleDetection:
    def __init__(self, encoding: str):
        self.encoding = encoding


class _SimpleDetectionResult:
    def __init__(self, detection: _SimpleDetection | None):
        self._detection = detection

    def best(self):
        return self._detection


def _detect_bytes(chunk: bytes):
    if from_bytes is not None:
        result = from_bytes(chunk)
        best = result.best()
        if best is not None:
            return result
    fallback = _fallback_detection(chunk)
    if fallback is not None:
        return _SimpleDetectionResult(_SimpleDetection(fallback))
    if b"\x00" in chunk:
        return _SimpleDetectionResult(None)
    try:
        chunk.decode("utf-8")
        return _SimpleDetectionResult(_SimpleDetection("utf-8"))
    except UnicodeDecodeError:
        return _SimpleDetectionResult(None)


def _looks_like_text(text: str) -> bool:
    if not text:
        return True
    bad = 0
    total = 0
    for ch in text:
        total += 1
        if ch in "\n\r\t\f\b":
            continue
        if unicodedata.category(ch).startswith("C"):
            bad += 1
    return bad / max(total, 1) <= 0.02


def _fallback_detection(chunk: bytes) -> str | None:
    if b"\x00" in chunk:
        return None
    for encoding in _FALLBACK_ENCODINGS:
        try:
            text = chunk.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_like_text(text):
            return encoding
    return None


def is_text_file(path: str, sample_size: int = 8192) -> bool:
    """Return True if the file appears to be a text file.

    Reads the first sample_size bytes and uses charset-normalizer
    to detect whether the content is text in any encoding.
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
    except OSError:
        logger.warning("Cannot read file for detection: %s", path)
        return False
    if not chunk:
        return True  # empty files are text
    result = _detect_bytes(chunk).best()
    return result is not None


def detect_encoding(path: str, sample_size: int = 8192) -> str | None:
    """Detect the encoding of a file, or None if binary/undetectable."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
    except OSError:
        return None
    if not chunk:
        return None
    result = _detect_bytes(chunk).best()
    if result is None:
        return None
    return result.encoding


def get_mime_type(path: str) -> str | None:
    """Return the MIME type for a file path based on its extension, or None."""
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type


def is_image_file(path: str) -> bool:
    """Return True if the file's MIME type starts with 'image/'."""
    mime_type = get_mime_type(path)
    return mime_type is not None and mime_type.startswith("image/")


def is_video_file(path: str) -> bool:
    """Return True if the file's MIME type starts with 'video/'."""
    mime_type = get_mime_type(path)
    return mime_type is not None and mime_type.startswith("video/")
