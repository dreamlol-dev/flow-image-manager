"""
test_folder_scanner.py — Tests for the FolderScanner component.
"""

import pytest
from pathlib import Path
from PIL import Image

from app.core.folder_scanner import FolderScanner
from app.models.image_record import ImageStatus
from tests.conftest import make_image


class TestFolderScanner:

    def _scanner(self, tmp_path) -> FolderScanner:
        return FolderScanner(thumbnail_size=64, thumbnail_cache_dir=None)

    # ------------------------------------------------------------------
    # Basic scanning
    # ------------------------------------------------------------------

    def test_valid_input_folder(self, tmp_input, sample_jpeg, sample_png):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        assert result.total_valid == 2
        assert result.total_skipped == 0
        assert len(result.records) == 2

    def test_empty_input_folder(self, tmp_input):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        assert result.total_found == 0
        assert result.total_valid == 0
        assert result.records == []

    def test_missing_input_folder(self, tmp_path):
        scanner = FolderScanner()
        missing = tmp_path / "does_not_exist"
        result = scanner.scan(missing)
        assert result.total_valid == 0
        assert any("does not exist" in w for w in result.warnings)

    # ------------------------------------------------------------------
    # Supported formats
    # ------------------------------------------------------------------

    def test_jpeg_supported(self, tmp_input, sample_jpeg):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        names = [r.filename for r in result.records]
        assert sample_jpeg.name in names

    def test_png_supported(self, tmp_input, sample_png):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        names = [r.filename for r in result.records]
        assert sample_png.name in names

    def test_webp_supported(self, tmp_input, sample_webp):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        names = [r.filename for r in result.records]
        assert sample_webp.name in names

    def test_unsupported_files_excluded(self, tmp_input, text_file):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        names = [r.filename for r in result.records]
        assert text_file.name not in names

    # ------------------------------------------------------------------
    # Invalid images
    # ------------------------------------------------------------------

    def test_corrupted_image_marked_failed(self, tmp_input, corrupted_image):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        failed = [r for r in result.records if r.status == ImageStatus.FAILED]
        assert len(failed) == 1
        assert failed[0].filename == corrupted_image.name

    def test_scan_continues_after_invalid(
        self, tmp_input, corrupted_image, sample_jpeg
    ):
        """One bad file must not terminate the entire scan."""
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        assert result.total_valid >= 1   # the JPEG is valid

    def test_empty_file_marked_failed(self, tmp_input, empty_file):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        failed = [r for r in result.records if r.status == ImageStatus.FAILED]
        assert any(r.filename == empty_file.name for r in failed)

    # ------------------------------------------------------------------
    # Output folder exclusion
    # ------------------------------------------------------------------

    def test_output_inside_input_excluded(self, tmp_path):
        input_dir = tmp_path / "images"
        input_dir.mkdir()
        output_dir = input_dir / "processed"
        output_dir.mkdir()

        # Put one image in input, one in output
        make_image(input_dir / "a.jpg")
        make_image(output_dir / "b.jpg")

        scanner = FolderScanner()
        result = scanner.scan(input_dir, output_dir=output_dir)

        filenames = [r.filename for r in result.records]
        assert "a.jpg" in filenames
        assert "b.jpg" not in filenames

    def test_output_outside_input_not_excluded(self, tmp_path, tmp_input, tmp_output, sample_jpeg):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input, output_dir=tmp_output)
        assert result.total_valid == 1

    # ------------------------------------------------------------------
    # Record properties
    # ------------------------------------------------------------------

    def test_record_has_dimensions(self, tmp_input, sample_jpeg):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        record = result.records[0]
        assert record.width == 1920
        assert record.height == 1080

    def test_record_has_file_size(self, tmp_input, sample_jpeg):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input)
        record = result.records[0]
        assert record.file_size > 0

    def test_record_preset_default(self, tmp_input, sample_jpeg):
        scanner = FolderScanner()
        result = scanner.scan(tmp_input, default_preset="B")
        assert result.records[0].preset_id == "B"

