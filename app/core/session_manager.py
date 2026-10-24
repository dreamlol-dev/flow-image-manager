"""
session_manager.py — SQLite-backed session persistence for Flow Image Manager.

Stores one ImageRecord per source image.  Supports save, load, resume,
retry, and change-detection for interrupted sessions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from app.models.image_record import ImageRecord, ImageStatus, ReviewStatus
from app.utils.logging_utils import get_logger

log = get_logger("session_manager")

_SCHEMA_VERSION = 1


class SessionManager:
    """
    Manages the processing session database (SQLite).

    The database lives in the output folder (or a configurable location)
    as ``flow_session.db``.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_connected()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path), check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
            log.info("Session database opened: %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            log.debug("Session database closed.")

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        """Create or upgrade the database schema."""
        conn = self._conn
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0

        if current < 1:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_records (
                    source_path    TEXT PRIMARY KEY,
                    filename       TEXT NOT NULL,
                    file_size      INTEGER DEFAULT 0,
                    file_mtime     REAL    DEFAULT 0,
                    file_hash      TEXT    DEFAULT '',
                    width          INTEGER DEFAULT 0,
                    height         INTEGER DEFAULT 0,
                    format         TEXT    DEFAULT '',
                    preset_id      TEXT    DEFAULT 'A',
                    status         TEXT    DEFAULT 'pending',
                    review_status  TEXT    DEFAULT 'none',
                    output_path    TEXT    DEFAULT '',
                    added_at       REAL    DEFAULT 0,
                    started_at     REAL    DEFAULT 0,
                    completed_at   REAL    DEFAULT 0,
                    attempts       INTEGER DEFAULT 0,
                    last_error     TEXT    DEFAULT '',
                    thumbnail_path TEXT    DEFAULT ''
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )
            conn.commit()
            log.debug("Database schema v%d created.", _SCHEMA_VERSION)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save_record(self, record: ImageRecord) -> None:
        """Insert or update a single record."""
        d = record.to_dict()
        self._ensure_connected()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO image_records (
                source_path, filename, file_size, file_mtime, file_hash,
                width, height, format, preset_id, status, review_status,
                output_path, added_at, started_at, completed_at,
                attempts, last_error, thumbnail_path
            ) VALUES (
                :source_path, :filename, :file_size, :file_mtime, :file_hash,
                :width, :height, :format, :preset_id, :status, :review_status,
                :output_path, :added_at, :started_at, :completed_at,
                :attempts, :last_error, :thumbnail_path
            )
            """,
            d,
        )
        self._conn.commit()

    def save_records(self, records: list[ImageRecord]) -> None:
        """Batch insert/update."""
        self._ensure_connected()
        rows = [r.to_dict() for r in records]
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO image_records (
                source_path, filename, file_size, file_mtime, file_hash,
                width, height, format, preset_id, status, review_status,
                output_path, added_at, started_at, completed_at,
                attempts, last_error, thumbnail_path
            ) VALUES (
                :source_path, :filename, :file_size, :file_mtime, :file_hash,
                :width, :height, :format, :preset_id, :status, :review_status,
                :output_path, :added_at, :started_at, :completed_at,
                :attempts, :last_error, :thumbnail_path
            )
            """,
            rows,
        )
        self._conn.commit()

    def load_all_records(self) -> list[ImageRecord]:
        """Return all records from the database."""
        self._ensure_connected()
        rows = self._conn.execute(
            "SELECT * FROM image_records ORDER BY added_at"
        ).fetchall()
        records = []
        for row in rows:
            try:
                records.append(ImageRecord.from_dict(dict(row)))
            except Exception as exc:
                log.warning("Skipping corrupt record: %s", exc)
        return records

    def load_record(self, source_path: str) -> Optional[ImageRecord]:
        """Return a single record by source path, or None."""
        self._ensure_connected()
        row = self._conn.execute(
            "SELECT * FROM image_records WHERE source_path = ?",
            (source_path,),
        ).fetchone()
        if row:
            return ImageRecord.from_dict(dict(row))
        return None

    def delete_record(self, source_path: str) -> None:
        """Remove a record from the database."""
        self._ensure_connected()
        self._conn.execute(
            "DELETE FROM image_records WHERE source_path = ?",
            (source_path,),
        )
        self._conn.commit()

    def clear_all_records(self) -> None:
        """Remove every record (does NOT delete files)."""
        self._ensure_connected()
        self._conn.execute("DELETE FROM image_records")
        self._conn.commit()
        log.info("Session cleared.")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        """Return a summary dict: total, completed, failed, remaining."""
        self._ensure_connected()
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM image_records GROUP BY status"
        ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = row["cnt"]
        total = sum(counts.values())
        completed = counts.get(ImageStatus.COMPLETED.value, 0)
        failed = counts.get(ImageStatus.FAILED.value, 0)
        skipped = counts.get(ImageStatus.SKIPPED.value, 0)
        remaining = total - completed - skipped
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "remaining": remaining,
        }

    def get_failed_records(self) -> list[ImageRecord]:
        """Return records with status == FAILED."""
        self._ensure_connected()
        rows = self._conn.execute(
            "SELECT * FROM image_records WHERE status = ?",
            (ImageStatus.FAILED.value,),
        ).fetchall()
        return [ImageRecord.from_dict(dict(r)) for r in rows]

    def get_pending_records(self) -> list[ImageRecord]:
        """Return records eligible for processing (READY or PENDING)."""
        self._ensure_connected()
        rows = self._conn.execute(
            "SELECT * FROM image_records WHERE status IN (?, ?) ORDER BY added_at",
            (ImageStatus.READY.value, ImageStatus.PENDING.value),
        ).fetchall()
        return [ImageRecord.from_dict(dict(r)) for r in rows]

    def reset_failed_to_ready(self) -> int:
        """Reset all FAILED records to READY for retry. Returns count."""
        self._ensure_connected()
        cursor = self._conn.execute(
            """
            UPDATE image_records
            SET status = ?, last_error = ''
            WHERE status = ?
            """,
            (ImageStatus.READY.value, ImageStatus.FAILED.value),
        )
        self._conn.commit()
        n = cursor.rowcount
        log.info("Reset %d failed record(s) to READY.", n)
        return n

    def reset_processing_to_ready(self) -> int:
        """
        Reset any PROCESSING records to READY.

        Called on startup to handle records that were interrupted mid-flight.
        """
        self._ensure_connected()
        cursor = self._conn.execute(
            """
            UPDATE image_records
            SET status = ?
            WHERE status = ?
            """,
            (ImageStatus.READY.value, ImageStatus.PROCESSING.value),
        )
        self._conn.commit()
        n = cursor.rowcount
        if n:
            log.info(
                "Recovered %d in-progress record(s) from previous session.", n
            )
        return n

    def has_interrupted_session(self) -> bool:
        """Return True if there are unfinished records in the database."""
        self._ensure_connected()
        row = self._conn.execute(
            """
            SELECT COUNT(*) as cnt FROM image_records
            WHERE status IN (?, ?, ?)
            """,
            (
                ImageStatus.READY.value,
                ImageStatus.PENDING.value,
                ImageStatus.PROCESSING.value,
            ),
        ).fetchone()
        return (row["cnt"] > 0) if row else False

