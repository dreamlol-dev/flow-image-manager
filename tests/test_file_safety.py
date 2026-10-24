"""
test_file_safety.py — Tests for safe output handling and file utilities.
"""

import pytest
from pathlib import Path

from app.utils.file_utils import (
    unique_output_path,
    atomic_write_bytes,
    atomic_copy_file,
    validate_output_file,
    cleanup_temp_files,
    cleanup_thumbnail_cache,
    cleanup_session_cache,
    is_safe_output_dir,
    output_is_inside_input,
    human_readable_size,
    file_hash,
    file_mtime,
)


class TestUniquePath:

    def test_no_conflict(self, tmp_path):
        path = unique_output_path(tmp_path, "image.jpg")
        assert path == tmp_path / "image.jpg"

    def test_one_conflict(self, tmp_path):
        (tmp_path / "image.jpg").write_bytes(b"x")
        path = unique_output_path(tmp_path, "image.jpg")
        assert path == tmp_path / "image_(1).jpg"

    def test_multiple_conflicts(self, tmp_path):
        for i in range(3):
            name = "image.jpg" if i == 0 else f"image_({i}).jpg"
            (tmp_path / name).write_bytes(b"x")
        path = unique_output_path(tmp_path, "image.jpg")
        assert path.name == "image_(3).jpg"

    def test_different_extension(self, tmp_path):
        (tmp_path / "scene.png").write_bytes(b"x")
        path = unique_output_path(tmp_path, "scene.png")
        assert path.name == "scene_(1).png"


class TestAtomicWrite:

    def test_write_creates_file(self, tmp_path):
        dest = tmp_path / "out.bin"
        atomic_write_bytes(dest, b"hello world")
        assert dest.exists()
        assert dest.read_bytes() == b"hello world"

    def test_write_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "sub" / "dir" / "file.bin"
        atomic_write_bytes(dest, b"data")
        assert dest.exists()

    def test_no_temp_files_left(self, tmp_path):
        dest = tmp_path / "out.bin"
        atomic_write_bytes(dest, b"data")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestAtomicCopy:

    def test_copy_creates_file(self, tmp_path, sample_jpeg):
        dest = tmp_path / "copy.jpg"
        atomic_copy_file(sample_jpeg, dest)
        assert dest.exists()
        assert dest.stat().st_size == sample_jpeg.stat().st_size

    def test_source_unchanged(self, tmp_path, sample_jpeg):
        original_size = sample_jpeg.stat().st_size
        original_hash = file_hash(sample_jpeg)
        dest = tmp_path / "copy.jpg"
        atomic_copy_file(sample_jpeg, dest)
        assert file_hash(sample_jpeg) == original_hash
        assert sample_jpeg.stat().st_size == original_size


class TestOutputValidation:

    def test_valid_file(self, tmp_path):
        f = tmp_path / "out.jpg"
        f.write_bytes(b"x" * 200)
        ok, msg = validate_output_file(f)
        assert ok

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "ghost.jpg"
        ok, msg = validate_output_file(f)
        assert not ok
        assert "does not exist" in msg

    def test_suspiciously_small_file(self, tmp_path):
        f = tmp_path / "tiny.jpg"
        f.write_bytes(b"x" * 5)
        ok, msg = validate_output_file(f, min_bytes=100)
        assert not ok
        assert "small" in msg


class TestSafeOutputDir:

    def test_safe_when_outside(self, tmp_path):
        inp = tmp_path / "input"
        out = tmp_path / "output"
        inp.mkdir(); out.mkdir()
        assert is_safe_output_dir(inp, out)

    def test_unsafe_when_inside(self, tmp_path):
        inp = tmp_path / "input"
        out = inp / "processed"
        inp.mkdir(); out.mkdir()
        assert not is_safe_output_dir(inp, out)

    def test_output_is_inside_input(self, tmp_path):
        inp = tmp_path / "input"
        out = inp / "output"
        inp.mkdir(); out.mkdir()
        assert output_is_inside_input(inp, out)


class TestCleanupTempFiles:

    def test_removes_tmp_files(self, tmp_path):
        for i in range(3):
            (tmp_path / f"file{i}.tmp").write_bytes(b"x")
        n = cleanup_temp_files(tmp_path)
        assert n == 3
        assert list(tmp_path.glob("*.tmp")) == []

    def test_leaves_other_files(self, tmp_path):
        (tmp_path / "keep.jpg").write_bytes(b"x")
        (tmp_path / "remove.tmp").write_bytes(b"x")
        cleanup_temp_files(tmp_path)
        assert (tmp_path / "keep.jpg").exists()


class TestHumanReadableSize:

    def test_bytes(self):
        assert "B" in human_readable_size(512)

    def test_kilobytes(self):
        assert "KB" in human_readable_size(2048)

    def test_megabytes(self):
        assert "MB" in human_readable_size(2 * 1024 * 1024)


class TestFileHash:

    def test_consistent(self, sample_jpeg):
        h1 = file_hash(sample_jpeg)
        h2 = file_hash(sample_jpeg)
        assert h1 == h2

    def test_different_files_differ(self, sample_jpeg, sample_png):
        h1 = file_hash(sample_jpeg)
        h2 = file_hash(sample_png)
        assert h1 != h2


class TestCacheCleanup:

    def test_cleanup_thumbnail_cache(self, tmp_path):
        thumb_dir = tmp_path / ".thumbcache"
        thumb_dir.mkdir()
        for i in range(5):
            (thumb_dir / f"scene_{i}_1024.thumb.png").write_bytes(b"dummy_thumbnail_data")

        assert len(list(thumb_dir.iterdir())) == 5
        removed = cleanup_thumbnail_cache(thumb_dir)
        assert removed == 5
        assert len(list(thumb_dir.iterdir())) == 0

    def test_cleanup_session_cache_preserves_images_and_settings(self, tmp_path):
        thumb_dir = tmp_path / ".thumbcache"
        thumb_dir.mkdir()
        (thumb_dir / "preview1.thumb.png").write_bytes(b"thumb")

        out_dir = tmp_path / "Output"
        out_dir.mkdir()
        # Finished output images
        (out_dir / "Scene 43_clean.png").write_bytes(b"final_image_data")
        # Stray temp file
        (out_dir / "tmp_123.tmp").write_bytes(b"stray_temp")

        # Fake settings file
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        settings_file = cfg_dir / "settings.json"
        settings_file.write_text('{"input_folder": "C:/input", "output_folder": "C:/output", "region_presets": {"A": {}}}')

        res = cleanup_session_cache(thumb_dir, out_dir)
        assert res["thumbnails"] == 1
        assert res["temp_files"] == 1

        # Check that finished output image is safe
        assert (out_dir / "Scene 43_clean.png").exists()
        assert (out_dir / "Scene 43_clean.png").read_bytes() == b"final_image_data"
        # Check that stray temp file is cleaned
        assert not (out_dir / "tmp_123.tmp").exists()
        # Check that settings and presets are safe
        assert settings_file.exists()
        assert "region_presets" in settings_file.read_text()


