"""
image_validator.py — Validate that image files can be opened and processed.

Performs format checking, dimension reading, and basic data validation
without modifying the source image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

from app.utils.logging_utils import get_logger

log = get_logger("image_validator")

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp"}
)
SUPPORTED_FORMATS: frozenset[str] = frozenset(
    {"JPEG", "PNG", "WEBP"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_supported_extension(path: Path) -> bool:
    """Return True if *path* has a supported image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def validate_image(
    path: Path,
) -> tuple[bool, str, dict]:
    """
    Attempt to open and verify an image file.

    Args:
        path: Path to the image file.

    Returns:
        (success, error_message, info_dict)

        info_dict contains:
            width, height, format, mode, file_size
        If *success* is False the info_dict may be empty.
    """
    info: dict = {}

    if not path.exists():
        return False, f"File does not exist: {path}", info

    if not path.is_file():
        return False, f"Path is not a file: {path}", info

    if not is_supported_extension(path):
        return (
            False,
            f"Unsupported extension '{path.suffix}'",
            info,
        )

    # Check the file has some content
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        return False, f"Cannot stat file: {exc}", info

    if file_size == 0:
        return False, "File is empty (0 bytes)", info

    # Attempt to open with Pillow
    try:
        with Image.open(path) as img:
            img.verify()  # cheap: checks headers and structure
    except UnidentifiedImageError:
        return False, "File is not a recognized image format", info
    except Exception as exc:
        return False, f"Image verification failed: {exc}", info

    # Re-open to read actual properties (verify() closes the file)
    try:
        with Image.open(path) as img:
            img.load()  # force full decode to catch corrupt data
            fmt = img.format or _infer_format(path)
            info = {
                "width": img.width,
                "height": img.height,
                "format": fmt,
                "mode": img.mode,
                "file_size": file_size,
            }
    except Exception as exc:
        return False, f"Cannot decode image data: {exc}", info

    if fmt not in SUPPORTED_FORMATS:
        return False, f"Format '{fmt}' is not supported", info

    if info["width"] <= 0 or info["height"] <= 0:
        return False, "Image has invalid dimensions", info

    log.debug(
        "Validated %s: %dx%d %s",
        path.name,
        info["width"],
        info["height"],
        fmt,
    )
    return True, "", info


def read_dimensions(path: Path) -> tuple[int, int] | None:
    """
    Quickly read image dimensions without full decode.

    Returns (width, height) or None on failure.
    """
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception as exc:
        log.debug("Cannot read dimensions from %s: %s", path.name, exc)
        return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _infer_format(path: Path) -> str:
    """Infer format from extension when Pillow doesn't set img.format."""
    ext_map = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
    }
    return ext_map.get(path.suffix.lower(), "UNKNOWN")

