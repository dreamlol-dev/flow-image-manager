"""
test_session_manager.py — Tests for SQLite session persistence.
"""

import time
import pytest
from pathlib import Path

from app.core.session_manager import SessionManager
from app.models.image_record import ImageRecord, ImageStatus, ReviewStatus


@pytest.fixture
def session(tmp_path) -> SessionManager:
    db = tmp_path / "test_session.db"
    return SessionManager(db)


@pytest.fixture
def basic_record() -> ImageRecord:
    return ImageRecord(
        source_path="/fake/path/scene_001.jpg",
        filename="scene_001.jpg",
        file_size=512000,
        file_mtime=1700000000.0,
        width=1920,
        height=1080,
        format="JPEG",
        preset_id="A",
        status=ImageStatus.READY,
    )


class TestSessionManager:

    def test_save_and_load_record(self, session, basic_record):
        session.save_record(basic_record)
        loaded = session.load_record(basic_record.source_path)
        assert loaded is not None
        assert loaded.filename == basic_record.filename
        assert loaded.status == ImageStatus.READY

    def test_load_all_records(self, session, basic_record):
        r2 = ImageRecord(
            source_path="/fake/path/scene_002.jpg",
            filename="scene_002.jpg",
            status=ImageStatus.PENDING,
        )
        session.save_records([basic_record, r2])
        all_records = session.load_all_records()
        assert len(all_records) == 2

    def test_save_overwrites_existing(self, session, basic_record):
        session.save_record(basic_record)
        basic_record.status = ImageStatus.COMPLETED
        session.save_record(basic_record)
        loaded = session.load_record(basic_record.source_path)
        assert loaded.status == ImageStatus.COMPLETED

    def test_stats_correctness(self, session):
        records = [
            ImageRecord(
                source_path=f"/fake/{i}.jpg",
                filename=f"{i}.jpg",
                status=s,
            )
            for i, s in enumerate([
                ImageStatus.COMPLETED,
                ImageStatus.COMPLETED,
                ImageStatus.FAILED,
                ImageStatus.READY,
                ImageStatus.PENDING,
            ])
        ]
        session.save_records(records)
        stats = session.get_stats()
        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["total"] == 5

    def test_reset_failed_to_ready(self, session):
        r = ImageRecord(
            source_path="/fake/fail.jpg",
            filename="fail.jpg",
            status=ImageStatus.FAILED,
            last_error="something broke",
        )
        session.save_record(r)
        n = session.reset_failed_to_ready()
        assert n == 1
        loaded = session.load_record(r.source_path)
        assert loaded.status == ImageStatus.READY
        assert loaded.last_error == ""

    def test_reset_processing_to_ready(self, session):
        r = ImageRecord(
            source_path="/fake/proc.jpg",
            filename="proc.jpg",
            status=ImageStatus.PROCESSING,
        )
        session.save_record(r)
        n = session.reset_processing_to_ready()
        assert n == 1
        loaded = session.load_record(r.source_path)
        assert loaded.status == ImageStatus.READY

    def test_has_interrupted_session_true(self, session, basic_record):
        session.save_record(basic_record)  # status = READY
        assert session.has_interrupted_session()

    def test_has_interrupted_session_false_when_all_done(self, session):
        r = ImageRecord(
            source_path="/fake/done.jpg",
            filename="done.jpg",
            status=ImageStatus.COMPLETED,
        )
        session.save_record(r)
        assert not session.has_interrupted_session()

    def test_clear_all_records(self, session, basic_record):
        session.save_record(basic_record)
        session.clear_all_records()
        all_records = session.load_all_records()
        assert all_records == []

    def test_delete_record(self, session, basic_record):
        session.save_record(basic_record)
        session.delete_record(basic_record.source_path)
        loaded = session.load_record(basic_record.source_path)
        assert loaded is None

    def test_get_failed_records(self, session):
        records = [
            ImageRecord(
                source_path=f"/fake/{i}.jpg",
                filename=f"{i}.jpg",
                status=ImageStatus.FAILED,
            )
            for i in range(3)
        ]
        records.append(
            ImageRecord(
                source_path="/fake/ok.jpg",
                filename="ok.jpg",
                status=ImageStatus.COMPLETED,
            )
        )
        session.save_records(records)
        failed = session.get_failed_records()
        assert len(failed) == 3

    def test_roundtrip_review_status(self, session, basic_record):
        basic_record.review_status = ReviewStatus.APPROVED
        session.save_record(basic_record)
        loaded = session.load_record(basic_record.source_path)
        assert loaded.review_status == ReviewStatus.APPROVED

