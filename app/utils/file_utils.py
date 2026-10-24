"""
file_utils.py — Safe filesystem helpers for Flow Image Manager.

Provides atomic file operations, unique-name generation, directory
validation, and temporary-file management so that source images are
never accidentally modified or overwritten.
"""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from app.utils.logging_utils import get_logger

log = get_logger("file_utils")


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: Path) -> None:
    """Create *path* and all parents if they do not exist."""
    path.mkdir(parents=True, exist_ok=True)


def is_safe_output_dir(input_dir: Path, output_dir: Path) -> bool:
    """
    Return True if *output_dir* is NOT inside *input_dir*.

    This prevents the scanner from picking up its own outputs.
    """
    try:
        output_dir.resolve().relative_to(input_dir.resolve())
        return False  # output is inside input — unsafe
    except ValueError:
        return True  # not a sub-path — safe


def output_is_inside_input(input_dir: Path, output_dir: Path) -> bool:
    """Return True when the output folder sits inside the input folder."""
    return not is_safe_output_dir(input_dir, output_dir)


def open_folder_in_explorer(path: Path) -> None:
    """Open *path* in Windows Explorer."""
    if path.exists():
        os.startfile(str(path))
    else:
        log.warning("Cannot open folder — does not exist: %s", path)


# ---------------------------------------------------------------------------
# Filename conflict resolution
# ---------------------------------------------------------------------------

def unique_output_path(destination: Path, filename: str) -> Path:
    """
    Return a path for *filename* inside *destination* that does not
    conflict with any existing file.

    Appends _(1), _(2), … before the extension until a free slot is found.
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = destination / filename
    counter = 1
    while candidate.exists():
        candidate = destination / f"{stem}_({counter}){suffix}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Atomic write helpers
# ---------------------------------------------------------------------------

def atomic_write_bytes(destination: Path, data: bytes) -> None:
    """
    Write *data* to *destination* atomically using a temp file + rename.

    Raises ``IOError`` if the write or rename fails.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=destination.parent, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # Windows does not support atomic rename over an existing file;
        # use replace() which is as close to atomic as Windows allows.
        Path(tmp_path).replace(destination)
        log.debug("Atomic write completed: %s", destination)
    except Exception:
        # Clean up temp file if anything goes wrong
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_copy_file(source: Path, destination: Path) -> None:
    """
    Copy *source* to *destination* atomically.
    The source file is never modified.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=destination.parent, suffix=".tmp"
    )
    try:
        os.close(fd)
        shutil.copy2(str(source), tmp_path)
        Path(tmp_path).replace(destination)
        log.debug("Atomic copy: %s → %s", source, destination)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# File integrity helpers
# ---------------------------------------------------------------------------

def file_hash(path: Path, algorithm: str = "sha256") -> str:
    """
    Compute a hex digest of *path* using *algorithm*.

    Used to detect whether a source file has been modified since the
    last processing session.
    """
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_mtime(path: Path) -> float:
    """Return the modification timestamp of *path* as a float."""
    return path.stat().st_mtime


def file_size(path: Path) -> int:
    """Return the size of *path* in bytes."""
    return path.stat().st_size


def validate_output_file(path: Path, min_bytes: int = 100) -> tuple[bool, str]:
    """
    Basic validation of a freshly written output file.

    Returns (True, "") if valid, (False, reason) otherwise.
    """
    if not path.exists():
        return False, "Output file does not exist"
    size = path.stat().st_size
    if size < min_bytes:
        return False, f"Output file is suspiciously small ({size} bytes)"
    # Try to re-open the file to confirm it is readable
    try:
        with path.open("rb") as f:
            f.read(16)
    except OSError as exc:
        return False, f"Cannot re-read output file: {exc}"
    return True, ""


# ---------------------------------------------------------------------------
# Temp file and cache cleanup
# ---------------------------------------------------------------------------

def cleanup_temp_files(directory: Path, pattern: str = "*.tmp") -> int:
    """
    Remove temporary files matching *pattern* from *directory*.

    Returns the number of files removed.
    """
    if not directory.exists() or not directory.is_dir():
        return 0
    removed = 0
    for tmp in directory.glob(pattern):
        try:
            tmp.unlink()
            removed += 1
            log.debug("Removed temp file: %s", tmp)
        except OSError as exc:
            log.warning("Could not remove temp file %s: %s", tmp, exc)
    return removed


def cleanup_thumbnail_cache(cache_dir: Path) -> int:
    """
    Remove all cached thumbnail files inside *cache_dir* to prevent disk growth.

    Returns the count of removed files.
    """
    if not cache_dir.exists() or not cache_dir.is_dir():
        return 0
    removed = 0
    for file_path in cache_dir.iterdir():
        if file_path.is_file():
            try:
                file_path.unlink()
                removed += 1
                log.debug("Removed cached thumbnail: %s", file_path.name)
            except OSError as exc:
                log.warning("Could not remove thumbnail %s: %s", file_path.name, exc)
    if removed > 0:
        log.info("Cleared %d thumbnail file(s) from %s", removed, cache_dir)
    return removed


def cleanup_session_cache(
    thumb_dir: Path, output_dir: Optional[Path] = None
) -> dict[str, int]:
    """
    Purge thumbnails and leftover temp files to reclaim disk space.

    Preserves settings, input/output folder configurations, and user presets.
    """
    thumbs = cleanup_thumbnail_cache(thumb_dir)
    tmps = 0
    if output_dir and output_dir.exists() and output_dir.is_dir():
        tmps = cleanup_temp_files(output_dir)
    return {"thumbnails": thumbs, "temp_files": tmps}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def human_readable_size(size_bytes: int) -> str:
    """Return *size_bytes* formatted as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def is_symlink_safe(path: Path) -> bool:
    """
    Return True if *path* is not a symlink (or if it points outside
    the parent directory tree — simple cycle-guard).
    """
    if not path.is_symlink():
        return True
    target = path.resolve()
    parent = path.parent.resolve()
    # Allow only if the resolved target is not an ancestor of the parent
    try:
        parent.relative_to(target)
        return False  # target is an ancestor → potential loop
    except ValueError:
        return True

