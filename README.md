# Flow Image Manager

[![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-0078d4?logo=windows)](https://microsoft.com)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-3776ab?logo=python)](https://python.org)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20(Qt)-41cd52?logo=qt)](https://qt.io)
[![Engine](https://img.shields.io/badge/Engine-OpenCV%20%7C%20Pillow-5c3ee8?logo=opencv)](https://opencv.org)
[![Tests](https://img.shields.io/badge/Tests-90%20Passed-success)](tests/)

A modern, high-performance Windows desktop application designed to inspect, manage, and batch-process scene images generated for YouTube videos using **Google Flow**.

Flow Image Manager eliminates repetitive manual editing by automatically detecting and processing known mark layouts in scene images using authorized local computer vision inpainting.

---

## Key Features

- **Google Flow Layout Presets**:
  - **Preset A (Single Region)**: Calibrated for scene images with a single mark located near the bottom-right corner.
  - **Preset B (Double Region)**: Calibrated for scenes with dual marks (upper larger mark and lower smaller mark).
  - **Resolution-Independent**: Uses normalized `[0.0 .. 1.0]` coordinates that scale across different dimensions and aspect ratios (720p, 1080p, 4K, 16:9, 9:16).
  - **Interactive Visual Calibration**: Calibrate or adjust region boxes directly in the settings preview canvas.
- **Local Inpainting Engine**: Powered by OpenCV's Fast Marching inpainting (`cv2.INPAINT_TELEA`). 100% local, offline, and secure — no cloud API keys or external services required.
- **Symmetrical Desktop UI**: Built with PySide6 (Qt) featuring an obsidian dark theme, vector SVG icons, responsive layout cards, and high-contrast status pills.
- **Interactive Image Inspection**:
  - Pan & zoom preview canvas (mouse drag, scroll wheel, zoom buttons, Fit-to-Window).
  - Region overlay toggle (`Overlays ✓`) to visually verify mark positions on any image.
- **Zero Disk Bloat & Smart Cache Management**:
  - Generated thumbnails (`.thumbcache/`) and orphaned `.tmp` files are automatically purged when clicking **Clear Session** or **closing the application**.
  - Folder preferences (`input_folder`, `output_folder`) and calibrated watermark preset definitions are safely preserved in `config/settings.json`.
- **Atomic File Safety**:
  - Source files are strictly read-only and never modified or overwritten.
  - Outputs are written via atomic temporary files with automatic conflict handling (`skip`, `unique`, `ask`).
  - Safe directory validation prevents recursive folder processing.
- **Crash Recovery & Session Persistence**: SQLite session engine tracks image state (`Ready`, `Processing`, `Completed`, `Failed`, `Needs Review`, `Skipped`) with pause, resume, stop, and retry support.

---

## System Requirements

| Requirement | Supported Version |
|---|---|
| Operating System | Windows 11 / Windows 10 (64-bit) |
| Python (if running from source) | Python 3.11, 3.12, or 3.13 |
| Standalone Executable | No Python installation required |

---

## Quick Start

### Option 1: Standalone Windows Executable (Recommended)

1. Download or clone this repository.
2. Launch `dist\FlowImageManager.exe`.
3. Select your **Input Folder** containing your raw Google Flow scenes.
4. Select your **Output Folder** for clean exports.
5. Click **Scan Images** and then **Start Batch**.

### Option 2: Running from Source

1. Clone the repository:
   ```cmd
   git clone https://github.com/dreamlol-dev/flow-image-manager.git
   cd flow-image-manager
   ```

2. (Optional) Create and activate a virtual environment:
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install required dependencies:
   ```cmd
   pip install -r requirements.txt
   ```

4. Launch the application:
   ```cmd
   run.bat
   ```
   *(Or run `python main.py`)*

---

## Building the Executable (.exe)

You can package the application into a single standalone `.exe` using PyInstaller:

```cmd
build.bat
```

Or manually via command line:

```cmd
python -m PyInstaller ^
    --name "FlowImageManager" ^
    --onefile ^
    --windowed ^
    --clean ^
    --add-data "config;config" ^
    --add-data "app;app" ^
    --hidden-import "PySide6.QtCore" ^
    --hidden-import "PySide6.QtGui" ^
    --hidden-import "PySide6.QtWidgets" ^
    --hidden-import "PySide6.QtSvg" ^
    --hidden-import "cv2" ^
    --hidden-import "PIL" ^
    main.py
```

The resulting executable is generated in the `dist/` directory:
```
dist\FlowImageManager.exe
```

---

## Project Structure

```
FlowImageManager/
│
├── main.py                     # Application entry point & dependency validation
├── requirements.txt            # Python dependencies (PySide6, Pillow, OpenCV, pytest)
├── build.bat                   # Standalone PyInstaller build script
├── run.bat                     # Windows quick-launch runner
├── README.md                   # Application documentation
├── .gitignore                  # Git exclusions for clean repository releases
│
├── app/
│   ├── models/
│   │   └── image_record.py     # ImageRecord dataclass and lifecycle status enums
│   │
│   ├── core/
│   │   ├── batch_manager.py    # Background QThread worker with pause/resume/stop
│   │   ├── folder_scanner.py   # Multi-format scanner (JPG, PNG, WEBP) & safety checks
│   │   ├── image_processor.py  # Local inpainting engine (OpenCV Telea algorithm)
│   │   ├── image_validator.py  # File integrity, header, and dimension validation
│   │   ├── region_config.py    # Presets A & B with normalized region coordinate math
│   │   ├── session_manager.py  # SQLite session persistence & crash recovery
│   │   └── settings_manager.py # JSON configuration management (settings.json)
│   │
│   ├── ui/
│   │   ├── main_window.py      # Primary window layout, controls, and workspace
│   │   ├── components.py       # Custom widgets, Dark Obsidian QSS, StatCards, Badges
│   │   ├── image_preview.py    # Zoomable & pannable preview canvas with overlays
│   │   ├── settings_dialog.py  # Configuration modal & interactive region editor
│   │   └── icons.py            # SVG vector icons generator
│   │
│   └── utils/
│       ├── file_utils.py       # Atomic writes, temp cleanup, hashing, cache purge
│       └── logging_utils.py    # Rotating file logger and console formatting
│
├── config/
│   └── settings.json           # Default configuration & calibrated region presets
│
├── dist/
│   └── FlowImageManager.exe    # Standalone 64-bit Windows executable
│
└── tests/
    ├── test_file_safety.py     # Atomic write, cleanup, and cache tests
    ├── test_folder_scanner.py  # Folder recursion and output exclusion tests
    ├── test_image_validator.py # Image corruption and format tests
    ├── test_region_config.py   # Normalized coordinate scaling tests
    └── test_session_manager.py # SQLite queue and transaction tests
```

---

## Running the Automated Test Suite

The project includes 90 unit and integration tests covering file safety, image validation, folder scanning, region calculation, and database persistence:

```cmd
pytest tests/ -v
```

Expected output:
```
============================== 90 passed in 3.4s ==============================
```

---

## Watermark & Mark Attribution Policy

Flow Image Manager is designed for processing creator-owned YouTube video scene images. If an image contains required legal attribution, provenance credentials, or license watermarks, preserve it or obtain an authorized export from the upstream provider.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
