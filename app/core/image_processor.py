"""
image_processor.py — Modular image-processing engine for Flow Image Manager.

Architecture:
  AbstractImageEngine  — interface every engine must implement
  LocalInpaintEngine   — OpenCV-based inpainting to fill the mark regions
  ProcessingResult     — result container

The batch manager calls engines through the abstract interface.
No engine simulates success — if processing cannot complete, it raises.
"""

from __future__ import annotations

import abc
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from app.core.region_config import LayoutPreset, NormalizedRegion
from app.utils.logging_utils import get_logger

log = get_logger("image_processor")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ProcessingResult:
    """Returned by every engine after a processing attempt."""
    success: bool = False
    output_image: Optional[Image.Image] = None
    error_message: str = ""
    engine_name: str = ""
    duration_s: float = 0.0
    notes: str = ""

    def __bool__(self) -> bool:
        return self.success


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class AbstractImageEngine(abc.ABC):
    """
    Abstract base class for image-processing engines.

    All engines must implement every abstract method.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable engine name."""

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """
        Check whether this engine can operate.

        Returns:
            (True, "") if available.
            (False, reason) if unavailable.
        """

    @abc.abstractmethod
    def validate_request(
        self, source_path: Path, preset: LayoutPreset
    ) -> tuple[bool, str]:
        """
        Validate that the requested operation is feasible before processing.

        Returns:
            (True, "") if valid.
            (False, reason) if not.
        """

    @abc.abstractmethod
    def process(
        self, source_path: Path, preset: LayoutPreset
    ) -> ProcessingResult:
        """
        Process *source_path* according to *preset*.

        Must NOT modify the source file.
        Returns a ProcessingResult with output_image set if successful.
        """


# ---------------------------------------------------------------------------
# Local inpainting engine
# ---------------------------------------------------------------------------

class LocalInpaintEngine(AbstractImageEngine):
    """
    Uses OpenCV's Telea inpainting algorithm to fill mark regions.

    Regions defined in the preset are converted to pixel coordinates,
    a binary mask is created, and cv2.inpaint() fills those areas.
    The engine works entirely in-process and requires no network access.
    """

    _NAME = "Local Inpaint (OpenCV/Telea)"

    @property
    def name(self) -> str:
        return self._NAME

    def is_available(self) -> tuple[bool, str]:
        try:
            _ = cv2.__version__
            return True, ""
        except Exception as exc:
            return False, f"OpenCV unavailable: {exc}"

    def validate_request(
        self, source_path: Path, preset: LayoutPreset
    ) -> tuple[bool, str]:
        if not source_path.exists():
            return False, f"Source file not found: {source_path}"
        ok, msg = preset.validate()
        if not ok:
            return False, f"Preset invalid: {msg}"
        return True, ""

    def process(
        self, source_path: Path, preset: LayoutPreset
    ) -> ProcessingResult:
        t0 = time.monotonic()

        # Load image via Pillow (handles all supported formats)
        try:
            pil_img = Image.open(source_path)
            pil_img.load()
        except Exception as exc:
            return ProcessingResult(
                success=False,
                error_message=f"Cannot open source image: {exc}",
                engine_name=self._NAME,
            )

        # Convert to RGBA for safe processing
        original_mode = pil_img.mode
        has_alpha = original_mode in ("RGBA", "LA", "PA")
        work_img = pil_img.convert("RGBA")

        img_w, img_h = work_img.size

        # Build inpaint mask (white = fill, black = keep)
        mask = np.zeros((img_h, img_w), dtype=np.uint8)

        for region in preset.regions:
            ok, err = region.validate()
            if not ok:
                log.warning("Skipping invalid region: %s", err)
                continue
            left, top, right, bottom = region.to_pixel_rect(img_w, img_h)
            # Clamp to image bounds
            left = max(0, left)
            top = max(0, top)
            right = min(img_w, right)
            bottom = min(img_h, bottom)
            mask[top:bottom, left:right] = 255
            log.debug(
                "Region '%s': pixel rect (%d,%d,%d,%d)",
                region.label, left, top, right, bottom,
            )

        if mask.max() == 0:
            return ProcessingResult(
                success=False,
                error_message="No valid regions to process — mask is empty.",
                engine_name=self._NAME,
            )

        # Convert PIL RGBA → OpenCV BGRA
        np_img = np.array(work_img, dtype=np.uint8)
        bgra = cv2.cvtColor(np_img, cv2.COLOR_RGBA2BGRA)

        # Separate alpha channel; inpaint operates on BGR only
        bgr = bgra[:, :, :3]
        alpha = bgra[:, :, 3]

        # Run inpainting
        try:
            inpainted_bgr = cv2.inpaint(
                bgr, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA
            )
        except cv2.error as exc:
            return ProcessingResult(
                success=False,
                error_message=f"OpenCV inpaint failed: {exc}",
                engine_name=self._NAME,
            )

        # Re-merge alpha
        inpainted_bgra = cv2.merge(
            [inpainted_bgr[:, :, 0],
             inpainted_bgr[:, :, 1],
             inpainted_bgr[:, :, 2],
             alpha]
        )

        # Convert back to PIL in the original mode
        result_rgba = Image.fromarray(
            cv2.cvtColor(inpainted_bgra, cv2.COLOR_BGRA2RGBA)
        )
        if not has_alpha:
            result_img = result_rgba.convert(original_mode)
        else:
            result_img = result_rgba

        duration = time.monotonic() - t0
        log.info(
            "Inpaint complete for %s in %.2fs (%dx%d)",
            source_path.name, duration, img_w, img_h,
        )

        return ProcessingResult(
            success=True,
            output_image=result_img,
            engine_name=self._NAME,
            duration_s=duration,
        )


# ---------------------------------------------------------------------------
# Engine registry
# ---------------------------------------------------------------------------

_AVAILABLE_ENGINES: list[AbstractImageEngine] = [
    LocalInpaintEngine(),
]


def get_default_engine() -> AbstractImageEngine:
    """Return the first available engine."""
    for engine in _AVAILABLE_ENGINES:
        available, _ = engine.is_available()
        if available:
            return engine
    raise RuntimeError("No image-processing engine is available.")


def list_engines() -> list[tuple[str, bool, str]]:
    """
    Return a list of (name, available, reason) for every registered engine.
    """
    result = []
    for engine in _AVAILABLE_ENGINES:
        available, reason = engine.is_available()
        result.append((engine.name, available, reason))
    return result

