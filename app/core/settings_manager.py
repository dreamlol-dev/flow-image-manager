"""
settings_manager.py — Application settings persistence via JSON.

All settings are stored in config/settings.json relative to the
project root.  Settings are loaded on startup and saved after changes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

from app.utils.logging_utils import get_logger

log = get_logger("settings_manager")

_DEFAULTS: dict = {
    # Folders
    "input_folder": "",
    "output_folder": "",

    # Formats
    "supported_formats": ["jpg", "jpeg", "png", "webp"],

    # Preset
    "default_preset": "A",

    # Region configurations — stored by preset_id
    "region_presets": {},

    # Review
    "require_manual_review": False,

    # Filename conflicts: "skip" | "unique" | "ask"
    "conflict_mode": "unique",

    # Processing
    "retry_limit": 2,
    "processing_timeout_s": 120,

    # Logging
    "log_verbosity": "INFO",

    # Thumbnails
    "thumbnail_size": 128,

    # Preview
    "preview_zoom_fit_on_select": True,
}


class SettingsManager:
    """
    Manages application settings stored in a JSON file.
    """

    def __init__(self, settings_path: Path) -> None:
        self._path = settings_path
        self._data: dict = copy.deepcopy(_DEFAULTS)
        self.load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load settings from disk.  Missing keys are filled with defaults."""
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge loaded values over defaults
                self._merge(self._data, loaded)
                log.info("Settings loaded from %s", self._path)
            except Exception as exc:
                log.warning("Cannot load settings (%s); using defaults.", exc)
        else:
            log.info("No settings file found; using defaults.")

    def save(self) -> None:
        """Write settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            log.debug("Settings saved to %s", self._path)
        except Exception as exc:
            log.error("Cannot save settings: %s", exc)

    def reset_to_defaults(self) -> None:
        """Restore factory defaults and save."""
        self._data = copy.deepcopy(_DEFAULTS)
        self.save()
        log.info("Settings reset to defaults.")

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_all(self) -> dict:
        return copy.deepcopy(self._data)

    def update(self, updates: dict) -> None:
        """Update multiple keys at once."""
        for k, v in updates.items():
            self._data[k] = v

    # ------------------------------------------------------------------
    # Typed convenience accessors
    # ------------------------------------------------------------------

    @property
    def input_folder(self) -> str:
        return self._data.get("input_folder", "")

    @input_folder.setter
    def input_folder(self, value: str) -> None:
        self._data["input_folder"] = value

    @property
    def output_folder(self) -> str:
        return self._data.get("output_folder", "")

    @output_folder.setter
    def output_folder(self, value: str) -> None:
        self._data["output_folder"] = value

    @property
    def default_preset(self) -> str:
        return self._data.get("default_preset", "A")

    @default_preset.setter
    def default_preset(self, value: str) -> None:
        self._data["default_preset"] = value

    @property
    def conflict_mode(self) -> str:
        return self._data.get("conflict_mode", "unique")

    @property
    def retry_limit(self) -> int:
        return int(self._data.get("retry_limit", 2))

    @property
    def thumbnail_size(self) -> int:
        return int(self._data.get("thumbnail_size", 128))

    @property
    def log_verbosity(self) -> str:
        return self._data.get("log_verbosity", "INFO")

    @property
    def require_manual_review(self) -> bool:
        return bool(self._data.get("require_manual_review", False))

    # ------------------------------------------------------------------
    # Region preset helpers
    # ------------------------------------------------------------------

    def get_region_presets(self) -> dict:
        return self._data.get("region_presets", {})

    def set_region_presets(self, presets: dict) -> None:
        self._data["region_presets"] = presets

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _merge(base: dict, override: dict) -> None:
        """Recursively merge *override* into *base* (in-place)."""
        for k, v in override.items():
            if (
                k in base
                and isinstance(base[k], dict)
                and isinstance(v, dict)
            ):
                SettingsManager._merge(base[k], v)
            else:
                base[k] = v

