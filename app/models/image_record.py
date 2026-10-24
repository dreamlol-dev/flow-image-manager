"""
image_record.py — Data model for a single image in the processing queue.

Uses a dataclass for clean field access.  Serialization to/from dict
is provided for SQLite and JSON compatibility.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class ImageStatus(str, Enum):
    """Processing lifecycle states for a queued image."""
    PENDING = "pending"          # added to queue, not yet examined
    READY = "ready"              # validated, ready for processing
    PROCESSING = "processing"    # currently being processed
    COMPLETED = "completed"      # successfully processed and saved
    FAILED = "failed"            # processing or validation failed
    NEEDS_REVIEW = "needs_review"  # requires manual approval
    SKIPPED = "skipped"          # user chose to skip


class ReviewStatus(str, Enum):
    """Manual-review decisions."""
    NONE = "none"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass
class ImageRecord:
    """
    Complete record for one image file in a processing session.

    All mutable state is stored here; the record is persisted to SQLite.
    """

    # ---- Identity ----
    source_path: str = ""
    filename: str = ""
    file_size: int = 0
    file_mtime: float = 0.0
    file_hash: str = ""

    # ---- Image properties ----
    width: int = 0
    height: int = 0
    format: str = ""   # "JPEG", "PNG", "WEBP" …

    # ---- Preset ----
    preset_id: str = "A"   # "A" or "B"

    # ---- Lifecycle ----
    status: ImageStatus = ImageStatus.PENDING
    review_status: ReviewStatus = ReviewStatus.NONE

    # ---- Output ----
    output_path: str = ""

    # ---- Timing ----
    added_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0

    # ---- Error tracking ----
    attempts: int = 0
    last_error: str = ""

    # ---- Internal ----
    thumbnail_path: str = ""   # path to cached thumbnail file

    # ---------------------------------------------------------------------------
    # Derived properties
    # ---------------------------------------------------------------------------

    @property
    def source(self) -> Path:
        return Path(self.source_path)

    @property
    def output(self) -> Path | None:
        return Path(self.output_path) if self.output_path else None

    @property
    def dimensions_str(self) -> str:
        if self.width and self.height:
            return f"{self.width} × {self.height}"
        return "Unknown"

    @property
    def is_done(self) -> bool:
        return self.status in (
            ImageStatus.COMPLETED,
            ImageStatus.FAILED,
            ImageStatus.SKIPPED,
        )

    @property
    def is_retryable(self) -> bool:
        return self.status == ImageStatus.FAILED

    # ---------------------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["review_status"] = self.review_status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ImageRecord":
        data = dict(data)
        data["status"] = ImageStatus(data.get("status", ImageStatus.PENDING.value))
        data["review_status"] = ReviewStatus(
            data.get("review_status", ReviewStatus.NONE.value)
        )
        # Accept extra keys gracefully
        valid = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in valid}
        return cls(**filtered)

