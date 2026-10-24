"""
conftest.py — Shared pytest fixtures for Flow Image Manager tests.
"""

import io
import pytest
from pathlib import Path
from PIL import Image


@pytest.fixture
def tmp_input(tmp_path) -> Path:
    """A temporary input directory."""
    d = tmp_path / "input"
    d.mkdir()
    return d


@pytest.fixture
def tmp_output(tmp_path) -> Path:
    """A temporary output directory."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def sample_jpeg(tmp_input) -> Path:
    """A valid 1920×1080 JPEG test image."""
    path = tmp_input / "scene_001.jpg"
    img = Image.new("RGB", (1920, 1080), color=(120, 80, 200))
    img.save(str(path), format="JPEG", quality=90)
    return path


@pytest.fixture
def sample_png(tmp_input) -> Path:
    """A valid 1280×720 PNG test image."""
    path = tmp_input / "scene_002.png"
    img = Image.new("RGB", (1280, 720), color=(50, 150, 80))
    img.save(str(path), format="PNG")
    return path


@pytest.fixture
def sample_webp(tmp_input) -> Path:
    """A valid 800×600 WebP test image."""
    path = tmp_input / "scene_003.webp"
    img = Image.new("RGB", (800, 600), color=(200, 100, 50))
    img.save(str(path), format="WEBP")
    return path


@pytest.fixture
def corrupted_image(tmp_input) -> Path:
    """A file with .jpg extension but invalid data."""
    path = tmp_input / "corrupted.jpg"
    path.write_bytes(b"NOT AN IMAGE DATA " * 20)
    return path


@pytest.fixture
def empty_file(tmp_input) -> Path:
    """A zero-byte file with .png extension."""
    path = tmp_input / "empty.png"
    path.write_bytes(b"")
    return path


@pytest.fixture
def text_file(tmp_input) -> Path:
    """A plain text file (unsupported format)."""
    path = tmp_input / "document.txt"
    path.write_text("Hello, world!")
    return path


def make_image(
    path: Path,
    width: int = 1920,
    height: int = 1080,
    fmt: str = "JPEG",
    color=(100, 100, 100),
) -> Path:
    """Helper to create a test image at an arbitrary path."""
    img = Image.new("RGB", (width, height), color=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), format=fmt)
    return path

