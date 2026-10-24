"""
batch_manager.py — Background batch processing engine for Flow Image Manager.

Runs as a QThread.  Emits Qt signals to communicate progress and results
to the main window without blocking the GUI.

Processing workflow per image:
  1. Confirm source file still exists.
  2. Confirm source file has not changed unexpectedly.
  3. Validate the image.
  4. Load the configured preset.
  5. Check whether manual review is required.
  6. Execute the processing engine.
  7. Validate the result.
  8. Save the output safely (atomic write).
  9. Update session record.
  10. Emit progress signal.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Callable

from PIL import Image
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from app.core.image_processor import AbstractImageEngine, ProcessingResult
from app.core.image_validator import validate_image
from app.core.region_config import RegionConfigManager
from app.core.session_manager import SessionManager
from app.models.image_record import ImageRecord, ImageStatus
from app.utils.file_utils import (
    atomic_write_bytes,
    file_mtime,
    unique_output_path,
    validate_output_file,
    human_readable_size,
)
from app.utils.logging_utils import get_logger

log = get_logger("batch_manager")

# Conflict modes
CONFLICT_SKIP = "skip"
CONFLICT_UNIQUE = "unique"
CONFLICT_ASK = "ask"


class BatchWorker(QThread):
    """
    QThread that processes images one at a time.

    Signals:
        progress_updated(completed, failed, remaining, current_filename, elapsed_s)
        image_processed(source_path, status, output_path, error)
        batch_finished(completed, failed, total_duration_s)
        log_message(level, message)
        review_required(source_path)   — emitted when an image needs review
    """

    progress_updated = Signal(int, int, int, str, float)
    image_processed = Signal(str, str, str, str)  # path, status, out_path, error
    batch_finished = Signal(int, int, float)
    log_message = Signal(str, str)  # level, message
    review_required = Signal(str)

    def __init__(
        self,
        records: list[ImageRecord],
        output_dir: Path,
        engine: AbstractImageEngine,
        session: SessionManager,
        region_mgr: RegionConfigManager,
        conflict_mode: str = CONFLICT_UNIQUE,
        retry_limit: int = 2,
        require_review: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._records = list(records)
        self._output_dir = output_dir
        self._engine = engine
        self._session = session
        self._region_mgr = region_mgr
        self._conflict_mode = conflict_mode
        self._retry_limit = retry_limit
        self._require_review = require_review

        # Thread control
        self._mutex = QMutex()
        self._paused = False
        self._stop_requested = False

        self._completed = 0
        self._failed = 0
        self._t_start: float = 0.0

    # ------------------------------------------------------------------
    # Control methods (called from GUI thread)
    # ------------------------------------------------------------------

    def pause(self) -> None:
        with QMutexLocker(self._mutex):
            self._paused = True
        log.info("Batch paused.")

    def resume(self) -> None:
        with QMutexLocker(self._mutex):
            self._paused = False
        log.info("Batch resumed.")

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop_requested = True
            self._paused = False  # unblock if paused
        log.info("Batch stop requested.")

    def _is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._paused

    def _is_stopped(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stop_requested

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._t_start = time.monotonic()
        total = len(self._records)
        log.info("Batch started: %d image(s).", total)

        for idx, record in enumerate(self._records):
            # Handle pause / stop
            while self._is_paused() and not self._is_stopped():
                self.msleep(200)

            if self._is_stopped():
                log.info("Batch stopped by user at image %d/%d.", idx + 1, total)
                break

            remaining = total - idx - 1
            elapsed = time.monotonic() - self._t_start
            self.progress_updated.emit(
                self._completed, self._failed, remaining, record.filename, elapsed
            )

            self._process_one(record)

        elapsed = time.monotonic() - self._t_start
        log.info(
            "Batch finished: %d completed, %d failed in %.1fs.",
            self._completed, self._failed, elapsed,
        )
        self.batch_finished.emit(self._completed, self._failed, elapsed)

    # ------------------------------------------------------------------
    # Per-image processing
    # ------------------------------------------------------------------

    def _process_one(self, record: ImageRecord) -> None:
        source = record.source
        self.log_message.emit("INFO", f"Processing: {record.filename}")

        # --- Step 1: Source still exists?
        if not source.exists():
            self._fail(record, "Source file no longer exists.")
            return

        # --- Step 2: Source unchanged?
        current_mtime = file_mtime(source)
        if record.file_mtime and abs(current_mtime - record.file_mtime) > 1.0:
            self._fail(record, "Source file has been modified since scanning.")
            return

        # --- Step 3: Retry limit
        if record.attempts >= self._retry_limit:
            self._fail(record, f"Retry limit ({self._retry_limit}) reached.")
            return

        # --- Step 4: Validate image
        ok, err, info = validate_image(source)
        if not ok:
            self._fail(record, f"Validation failed: {err}")
            return

        # --- Step 5: Load preset
        preset = self._region_mgr.get_preset(record.preset_id)
        if preset is None:
            self._fail(record, f"Unknown preset: {record.preset_id}")
            return

        ok, err = preset.validate()
        if not ok:
            self._fail(record, f"Preset invalid: {err}")
            return

        # --- Step 6: Review check
        if self._require_review and record.review_status.value == "none":
            record.status = ImageStatus.NEEDS_REVIEW
            self._session.save_record(record)
            self.review_required.emit(record.source_path)
            self.log_message.emit("INFO", f"Review required: {record.filename}")
            return

        # --- Step 7: Mark as processing
        record.status = ImageStatus.PROCESSING
        record.started_at = time.time()
        record.attempts += 1
        self._session.save_record(record)

        # --- Step 8: Execute engine
        ok_eng, reason = self._engine.is_available()
        if not ok_eng:
            self._fail(record, f"Engine unavailable: {reason}")
            return

        ok_val, reason = self._engine.validate_request(source, preset)
        if not ok_val:
            self._fail(record, f"Engine rejected request: {reason}")
            return

        result: ProcessingResult = self._engine.process(source, preset)

        if not result.success:
            self._fail(record, f"Engine error: {result.error_message}")
            return

        if result.output_image is None:
            self._fail(record, "Engine returned no output image.")
            return

        # --- Step 9: Determine output path
        output_path = self._resolve_output_path(record)
        if output_path is None:
            # Conflict mode = skip
            record.status = ImageStatus.SKIPPED
            record.last_error = "Output file already exists (skip mode)."
            self._session.save_record(record)
            self.image_processed.emit(
                record.source_path, record.status.value, "", record.last_error
            )
            return

        # --- Step 10: Save output atomically
        try:
            self._save_output(result.output_image, output_path, record.format)
        except Exception as exc:
            self._fail(record, f"Save failed: {exc}")
            return

        # --- Step 11: Validate output
        valid, msg = validate_output_file(output_path)
        if not valid:
            self._fail(record, f"Output validation failed: {msg}")
            return

        # --- Step 12: Mark completed
        record.status = ImageStatus.COMPLETED
        record.output_path = str(output_path)
        record.completed_at = time.time()
        self._session.save_record(record)
        self._completed += 1

        self.image_processed.emit(
            record.source_path, record.status.value, str(output_path), ""
        )
        self.log_message.emit(
            "INFO", f"Completed: {record.filename} → {output_path.name}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fail(self, record: ImageRecord, reason: str) -> None:
        record.status = ImageStatus.FAILED
        record.last_error = reason
        record.completed_at = time.time()
        self._session.save_record(record)
        self._failed += 1
        self.image_processed.emit(
            record.source_path, record.status.value, "", reason
        )
        self.log_message.emit("WARNING", f"Failed: {record.filename} — {reason}")

    def _resolve_output_path(self, record: ImageRecord) -> Optional[Path]:
        """
        Determine the output file path based on the conflict mode.

        Returns None when the image should be skipped.
        """
        candidate = self._output_dir / record.filename
        if not candidate.exists():
            return candidate

        if self._conflict_mode == CONFLICT_SKIP:
            return None
        elif self._conflict_mode == CONFLICT_UNIQUE:
            return unique_output_path(self._output_dir, record.filename)
        else:
            # CONFLICT_ASK: for now fall back to unique naming
            # (The UI layer can intercept review_required for interactive asks)
            return unique_output_path(self._output_dir, record.filename)

    def _save_output(
        self, img: Image.Image, output_path: Path, original_format: str
    ) -> None:
        """
        Save *img* to *output_path* using the appropriate format.

        Format is preserved from the original where possible.
        Uses an atomic temp-file write.
        """
        fmt = original_format.upper() if original_format else None

        # Determine save format and options
        save_kwargs: dict = {}
        if fmt == "JPEG":
            # JPEG cannot store alpha
            if img.mode in ("RGBA", "LA"):
                img = img.convert("RGB")
            save_kwargs = {"quality": 95, "optimize": True}
            ext = ".jpg"
        elif fmt == "PNG":
            save_kwargs = {"optimize": True}
            ext = ".png"
        elif fmt == "WEBP":
            save_kwargs = {"quality": 95, "lossless": False}
            ext = ".webp"
        else:
            # Default to PNG
            fmt = "PNG"
            ext = ".png"

        import io as _io
        buf = _io.BytesIO()
        img.save(buf, format=fmt, **save_kwargs)
        data = buf.getvalue()

        # Adjust extension if needed
        if output_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            output_path = output_path.with_suffix(ext)

        atomic_write_bytes(output_path, data)

