"""
region_config.py — Normalized region definitions for layout presets.

Regions are stored as normalized [0..1] floats so they apply correctly
to images of any resolution.  Pixel coordinates are computed at
runtime by multiplying against the actual image dimensions.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from app.utils.logging_utils import get_logger

log = get_logger("region_config")


# ---------------------------------------------------------------------------
# Region dataclass
# ---------------------------------------------------------------------------

@dataclass
class NormalizedRegion:
    """
    A rectangular region defined in normalized image coordinates.

    All values must be in [0.0, 1.0].
    x, y are the top-left corner.
    width and height extend toward the bottom-right.
    """
    x: float = 0.0
    y: float = 0.0
    width: float = 0.1
    height: float = 0.1
    label: str = ""

    def validate(self) -> tuple[bool, str]:
        """Return (True, "") if valid, else (False, reason)."""
        for attr in ("x", "y", "width", "height"):
            val = getattr(self, attr)
            if not (0.0 <= val <= 1.0):
                return False, f"{attr}={val} is outside [0, 1]"
        if self.x + self.width > 1.0:
            return False, f"x({self.x}) + width({self.width}) exceeds 1.0"
        if self.y + self.height > 1.0:
            return False, f"y({self.y}) + height({self.height}) exceeds 1.0"
        if self.width <= 0:
            return False, "width must be > 0"
        if self.height <= 0:
            return False, "height must be > 0"
        return True, ""

    def to_pixel_rect(
        self, img_width: int, img_height: int
    ) -> tuple[int, int, int, int]:
        """
        Convert to pixel rectangle (left, top, right, bottom).

        Args:
            img_width: Image pixel width.
            img_height: Image pixel height.

        Returns:
            (left, top, right, bottom) in pixel coordinates.
        """
        left = int(self.x * img_width)
        top = int(self.y * img_height)
        right = int((self.x + self.width) * img_width)
        bottom = int((self.y + self.height) * img_height)
        return left, top, right, bottom

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NormalizedRegion":
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            width=float(data.get("width", 0.1)),
            height=float(data.get("height", 0.1)),
            label=str(data.get("label", "")),
        )


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

@dataclass
class LayoutPreset:
    """
    A named preset containing one or two NormalizedRegion objects.
    """
    preset_id: str = "A"
    name: str = "Single Region"
    description: str = ""
    regions: list[NormalizedRegion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "preset_id": self.preset_id,
            "name": self.name,
            "description": self.description,
            "regions": [r.to_dict() for r in self.regions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutPreset":
        regions = [
            NormalizedRegion.from_dict(r) for r in data.get("regions", [])
        ]
        return cls(
            preset_id=str(data.get("preset_id", "A")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            regions=regions,
        )

    def validate(self) -> tuple[bool, str]:
        """Validate all contained regions."""
        if not self.regions:
            return False, f"Preset {self.preset_id} has no regions"
        for i, region in enumerate(self.regions):
            ok, msg = region.validate()
            if not ok:
                return False, f"Region {i} in preset {self.preset_id}: {msg}"
        return True, ""


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Preset A: single small mark, bottom-right corner
_DEFAULT_PRESET_A = LayoutPreset(
    preset_id="A",
    name="Single Region",
    description="One small mark near the bottom-right corner.",
    regions=[
        NormalizedRegion(x=0.9495, y=0.9093, width=0.0189, height=0.0351, label="mark"),
    ],
)

# Preset B: two marks stacked, bottom-right corner
_DEFAULT_PRESET_B = LayoutPreset(
    preset_id="B",
    name="Double Region",
    description="Two marks near the bottom-right corner: upper (larger) and lower (smaller).",
    regions=[
        NormalizedRegion(x=0.9108, y=0.8401, width=0.0374, height=0.0680, label="upper_mark"),
        NormalizedRegion(x=0.9495, y=0.9093, width=0.0189, height=0.0351, label="lower_mark"),
    ],
)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class RegionConfigManager:
    """
    Loads, saves, and provides access to layout presets.

    Presets are stored as JSON within the application settings file.
    """

    PRESET_IDS = ("A", "B")

    def __init__(self) -> None:
        self._presets: dict[str, LayoutPreset] = {
            "A": copy.deepcopy(_DEFAULT_PRESET_A),
            "B": copy.deepcopy(_DEFAULT_PRESET_B),
        }

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get_preset(self, preset_id: str) -> LayoutPreset | None:
        return self._presets.get(preset_id)

    def all_presets(self) -> list[LayoutPreset]:
        return list(self._presets.values())

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update_preset(self, preset: LayoutPreset) -> tuple[bool, str]:
        """Validate and store a preset."""
        ok, msg = preset.validate()
        if not ok:
            log.warning("Preset validation failed: %s", msg)
            return False, msg
        self._presets[preset.preset_id] = copy.deepcopy(preset)
        log.info("Preset %s updated: %s", preset.preset_id, preset.name)
        return True, ""

    def reset_to_defaults(self) -> None:
        """Restore factory defaults."""
        self._presets = {
            "A": copy.deepcopy(_DEFAULT_PRESET_A),
            "B": copy.deepcopy(_DEFAULT_PRESET_B),
        }
        log.info("Region presets reset to defaults.")

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {pid: p.to_dict() for pid, p in self._presets.items()}

    def from_dict(self, data: dict) -> None:
        """Load presets from a dict (typically from settings.json)."""
        for pid in self.PRESET_IDS:
            if pid in data:
                preset = LayoutPreset.from_dict(data[pid])
                self._presets[pid] = preset
                log.debug("Loaded preset %s from config.", pid)

