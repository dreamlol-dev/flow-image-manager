"""
main.py — Application entry point for Flow Image Manager.

Performs:
  1. Logging initialization.
  2. Environment checks (Python version, required packages).
  3. Settings and region-config loading.
  4. QApplication creation and stylesheet application.
  5. Main window display.
"""

import sys
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path (allows running from any CWD)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Logging (before any other app import)
# ---------------------------------------------------------------------------
from app.utils.logging_utils import setup_logging, get_logger

_LOG_DIR = _ROOT / "logs"
_logger = setup_logging(_LOG_DIR, verbosity="INFO")

# ---------------------------------------------------------------------------
# Environment check
# ---------------------------------------------------------------------------
_logger.info("=" * 60)
_logger.info("Flow Image Manager starting up.")
_logger.info("Python: %s", sys.version)
_logger.info("Project root: %s", _ROOT)


def _check_deps() -> list[str]:
    """Return a list of missing package names."""
    missing = []
    for pkg, import_name in [
        ("PySide6", "PySide6"),
        ("Pillow", "PIL"),
        ("opencv-python", "cv2"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    return missing


missing_deps = _check_deps()
if missing_deps:
    print(
        f"ERROR: Missing required packages: {', '.join(missing_deps)}\n"
        f"Run: pip install {' '.join(missing_deps)}\n"
        f"Or:  pip install -r requirements.txt"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# App imports (after dep check)
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.core.region_config import RegionConfigManager
from app.core.settings_manager import SettingsManager
from app.ui.components import APP_STYLESHEET
from app.ui.main_window import MainWindow

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Windows DPI awareness
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("Flow Image Manager")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Flow Tools")

    # Apply dark stylesheet
    app.setStyleSheet(APP_STYLESHEET)

    # Default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Settings
    settings_path = _ROOT / "config" / "settings.json"
    settings = SettingsManager(settings_path)

    # Update log verbosity from settings
    from app.utils.logging_utils import set_verbosity
    set_verbosity(settings.log_verbosity)

    # Region configuration
    region_mgr = RegionConfigManager()
    saved_presets = settings.get_region_presets()
    if saved_presets:
        region_mgr.from_dict(saved_presets)
        _logger.info("Loaded region presets from settings.")

    _logger.info("Settings loaded from: %s", settings_path)

    # Main window
    window = MainWindow(
        settings=settings,
        region_mgr=region_mgr,
        project_dir=_ROOT,
    )
    window.show()
    _logger.info("Main window displayed.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

