"""
folder_scanner.py — Discover and validate images in the input folder.

The scanner is designed to be run in a background thread.
It reports progress via a callback so the UI stays responsive.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from app.core.image_validator import is_supported_extension, validate_image
from app.models.image_record import ImageRecord, ImageStatus
from app.utils.file_utils import (
    file_hash,
    file_mtime,
    file_size,
    is_symlink_safe,
    output_is_inside_input,
)
from app.utils.logging_utils import get_logger

log = get_logger("folder_scanner")

# Thumbnail size in pixels (longest edge)
DEFAULT_THUMBNAIL_SIZE: int = 128


class ScanResult:
    """Container for the results of a folder scan."""

    def __init__(self) -> None:
        self.records: list[ImageRecord] = []
        self.skipped_paths: list[tuple[Path, str]] = []  # (path, reason)
        self.total_found: int = 0
        self.total_valid: int = 0
        self.total_skipped: int = 0
        self.scan_duration_s: float = 0.0
        self.warnings: list[str] = []

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        log.warning(msg)


class FolderScanner:
    """
    Scans a directory for supported image files and produces ImageRecord objects.

    Args:
        thumbnail_size: Pixel size (longest edge) for generated thumbnails.
        thumbnail_cache_dir: Directory for thumbnail cache files.
            If None, thumbnails are not cached to disk.
    """

    def __init__(
        self,
        thumbnail_size: int = DEFAULT_THUMBNAIL_SIZE,
        thumbnail_cache_dir: Optional[Path] = None,
    ) -> None:
        self._thumb_size = thumbnail_size
        self._thumb_cache = thumbnail_cache_dir
        self._cancelled = False

    def cancel(self) -> None:
        """Signal the scan to stop after the current file."""
        self._cancelled = True

    def scan(
        self,
        input_dir: Path,
        output_dir: Optional[Path] = None,
        existing_records: Optional[dict[str, ImageRecord]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        default_preset: str = "A",
    ) -> ScanResult:
        """
        Scan *input_dir* for images.

        Args:
            input_dir: Folder to scan.
            output_dir: Output folder; files inside it are excluded.
            existing_records: Dict of source_path → ImageRecord from a
                previous session.  Already-completed images are preserved.
            progress_cb: Called as (processed, total, current_filename).
            default_preset: Preset ID to assign to new records.

        Returns:
            ScanResult with all discovered records.
        """
        self._cancelled = False
        result = ScanResult()
        t0 = time.monotonic()

        if not input_dir.exists():
            result.add_warning(f"Input folder does not exist: {input_dir}")
            return result

        if not input_dir.is_dir():
            result.add_warning(f"Input path is not a directory: {input_dir}")
            return result

        # Warn if output is inside input
        if output_dir and output_is_inside_input(input_dir, output_dir):
            result.add_warning(
                "Output folder is inside the input folder. "
                "Output files will be excluded from scanning, but "
                "this configuration can cause confusion."
            )

        # Collect candidate paths
        candidates = self._collect_candidates(input_dir, output_dir, result)
        result.total_found = len(candidates)
        log.info(
            "Scanning %s — found %d candidate file(s).",
            input_dir,
            len(candidates),
        )

        existing = existing_records or {}

        for idx, img_path in enumerate(candidates):
            if self._cancelled:
                log.info("Scan cancelled after %d files.", idx)
                break

            if progress_cb:
                progress_cb(idx, len(candidates), img_path.name)

            # Try to get an existing record
            key = str(img_path)
            if key in existing:
                record = existing[key]
                # Re-use completed records only if the file hasn't changed
                if record.status == ImageStatus.COMPLETED:
                    current_mtime = file_mtime(img_path)
                    if abs(current_mtime - record.file_mtime) < 1.0:
                        result.records.append(record)
                        result.total_valid += 1
                        continue
                    else:
                        log.info(
                            "Source changed since last session: %s",
                            img_path.name,
                        )
                        # Fall through to re-validate
            else:
                record = ImageRecord(
                    source_path=str(img_path),
                    filename=img_path.name,
                    preset_id=default_preset,
                )

            # Validate the image
            ok, error, info = validate_image(img_path)
            if not ok:
                record.status = ImageStatus.FAILED
                record.last_error = error
                result.skipped_paths.append((img_path, error))
                result.total_skipped += 1
                log.warning("Invalid image %s: %s", img_path.name, error)
            else:
                record.file_size = info["file_size"]
                record.file_mtime = file_mtime(img_path)
                record.width = info["width"]
                record.height = info["height"]
                record.format = info["format"]
                if record.status not in (
                    ImageStatus.COMPLETED,
                    ImageStatus.SKIPPED,
                ):
                    record.status = ImageStatus.READY
                result.total_valid += 1

                # Generate thumbnail
                thumb_path = self._generate_thumbnail(img_path, record)
                if thumb_path:
                    record.thumbnail_path = str(thumb_path)

            result.records.append(record)

        result.scan_duration_s = time.monotonic() - t0
        log.info(
            "Scan complete in %.2fs: %d valid, %d skipped.",
            result.scan_duration_s,
            result.total_valid,
            result.total_skipped,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_candidates(
        self,
        input_dir: Path,
        output_dir: Optional[Path],
        result: ScanResult,
    ) -> list[Path]:
        """Return sorted list of supported image paths in *input_dir*."""
        candidates: list[Path] = []
        output_resolved = output_dir.resolve() if output_dir else None

        for entry in sorted(input_dir.iterdir()):
            if self._cancelled:
                break

            # Skip hidden files and system files
            if entry.name.startswith("."):
                continue

            # Skip symlinks that could create loops
            if entry.is_symlink() and not is_symlink_safe(entry):
                log.warning("Skipping potentially unsafe symlink: %s", entry)
                continue

            if entry.is_dir():
                # Never recurse into the output folder
                if output_resolved and entry.resolve() == output_resolved:
                    log.debug("Skipping output dir: %s", entry)
                    continue
                # Recurse into subdirectories (non-output)
                sub_result = ScanResult()
                sub_candidates = self._collect_candidates(
                    entry, output_dir, sub_result
                )
                candidates.extend(sub_candidates)
                result.warnings.extend(sub_result.warnings)

            elif entry.is_file() and is_supported_extension(entry):
                candidates.append(entry)

        return candidates

    def _generate_thumbnail(
        self, img_path: Path, record: ImageRecord
    ) -> Optional[Path]:
        """
        Generate and optionally cache a thumbnail.

        Returns the thumbnail path if cached, else None.
        """
        if not self._thumb_cache:
            return None

        self._thumb_cache.mkdir(parents=True, exist_ok=True)
        thumb_name = f"{img_path.stem}_{img_path.stat().st_size}.thumb.png"
        thumb_path = self._thumb_cache / thumb_name

        if thumb_path.exists():
            return thumb_path  # use cached version

        try:
            with Image.open(img_path) as img:
                img.thumbnail(
                    (self._thumb_size, self._thumb_size), Image.LANCZOS
                )
                img.save(str(thumb_path), format="PNG")
            return thumb_path
        except Exception as exc:
            log.debug("Thumbnail generation failed for %s: %s", img_path.name, exc)
            return None

