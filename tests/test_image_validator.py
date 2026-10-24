"""
test_image_validator.py — Tests for image_validator module.
"""

import pytest
from pathlib import Path
from PIL import Image

from app.core.image_validator import (
    is_supported_extension,
    validate_image,
    read_dimensions,
    SUPPORTED_EXTENSIONS,
)


class TestExtensionCheck:

    def test_jpg_supported(self, tmp_path):
        p = tmp_path / "x.jpg"
        assert is_supported_extension(p)

    def test_jpeg_supported(self, tmp_path):
        p = tmp_path / "x.jpeg"
        assert is_supported_extension(p)

    def test_png_supported(self, tmp_path):
        p = tmp_path / "x.png"
        assert is_supported_extension(p)

    def test_webp_supported(self, tmp_path):
        p = tmp_path / "x.webp"
        assert is_supported_extension(p)

    def test_txt_not_supported(self, tmp_path):
        p = tmp_path / "x.txt"
        assert not is_supported_extension(p)

    def test_bmp_not_supported(self, tmp_path):
        p = tmp_path / "x.bmp"
        assert not is_supported_extension(p)

    def test_case_insensitive(self, tmp_path):
        p = tmp_path / "x.JPG"
        assert is_supported_extension(p)


class TestValidateImage:

    def test_valid_jpeg(self, sample_jpeg):
        ok, err, info = validate_image(sample_jpeg)
        assert ok
        assert err == ""
        assert info["width"] == 1920
        assert info["height"] == 1080

    def test_valid_png(self, sample_png):
        ok, err, info = validate_image(sample_png)
        assert ok
        assert info["format"] == "PNG"

    def test_file_not_exist(self, tmp_path):
        p = tmp_path / "ghost.jpg"
        ok, err, info = validate_image(p)
        assert not ok
        assert "does not exist" in err

    def test_empty_file(self, empty_file):
        ok, err, info = validate_image(empty_file)
        assert not ok
        assert "empty" in err.lower() or len(err) > 0

    def test_corrupted_file(self, corrupted_image):
        ok, err, info = validate_image(corrupted_image)
        assert not ok
        assert len(err) > 0

    def test_unsupported_extension(self, text_file):
        ok, err, info = validate_image(text_file)
        assert not ok
        assert "Unsupported" in err or "extension" in err.lower()

    def test_returns_format(self, sample_jpeg):
        ok, err, info = validate_image(sample_jpeg)
        assert info.get("format") in ("JPEG",)

    def test_returns_file_size(self, sample_jpeg):
        ok, err, info = validate_image(sample_jpeg)
        assert info.get("file_size", 0) > 0


class TestReadDimensions:

    def test_valid_jpeg(self, sample_jpeg):
        dims = read_dimensions(sample_jpeg)
        assert dims == (1920, 1080)

    def test_valid_png(self, sample_png):
        dims = read_dimensions(sample_png)
        assert dims == (1280, 720)

    def test_invalid_file(self, corrupted_image):
        dims = read_dimensions(corrupted_image)
        assert dims is None

    def test_nonexistent_file(self, tmp_path):
        p = tmp_path / "nope.jpg"
        dims = read_dimensions(p)
        assert dims is None

