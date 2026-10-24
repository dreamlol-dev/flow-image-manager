"""
main_window.py — Primary application window for Flow Image Manager.

Layout (top-to-bottom):
  ┌─ Header bar (title · engine status · Settings / Logs buttons) ─────────┐
  ├─ Symmetrical folder row (Input selector | Output selector) ────────────┤
  ├─ Stats row (Total / Completed / Failed / Remaining cards) ─────────────┤
  ├─ Workspace splitter ────────────────────────────────────────────────────│
  │   Left  → Image queue (header + styled list)                           │
  │   Right → Preview panel (zoomable image + info bar + review bar)       │
  ├─ Controls bar (Start / Pause / Resume / Stop / Retry / Clear) ─────────┤
  └─ Progress section (bar + live metric badges) ──────────────────────────┘
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QImage
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QSizePolicy, QSplitter, QStatusBar,
    QVBoxLayout, QWidget,
)

from app.core.batch_manager import BatchWorker, CONFLICT_SKIP, CONFLICT_UNIQUE
from app.core.folder_scanner import FolderScanner, ScanResult
from app.core.image_processor import get_default_engine, list_engines
from app.core.region_config import RegionConfigManager
from app.core.session_manager import SessionManager
from app.core.settings_manager import SettingsManager
from app.models.image_record import ImageRecord, ImageStatus
from app.ui.components import (
    APP_STYLESHEET, PALETTE, FolderSelector, ProgressSection,
    SectionHeader, StatCard, StatusBadge,
)
from app.ui.icons import get_icon, get_pixmap
from app.ui.image_preview import ImagePreviewWidget
from app.ui.settings_dialog import SettingsDialog
from app.utils.file_utils import (
    human_readable_size, ensure_dir, cleanup_session_cache, cleanup_thumbnail_cache
)
from app.utils.logging_utils import get_logger, get_log_dir

log = get_logger("main_window")


# ─────────────────────────────────────────────────────────────────────────────
# Background scan thread
# ─────────────────────────────────────────────────────────────────────────────

class ScanWorker(QThread):
    """Wraps FolderScanner for background execution."""

    scan_complete = Signal(object)    # ScanResult
    progress      = Signal(int, int, str)
    error         = Signal(str)

    def __init__(
        self,
        input_dir: Path,
        output_dir: Optional[Path],
        existing: dict,
        thumb_dir: Optional[Path],
        thumb_size: int,
        default_preset: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._input_dir      = input_dir
        self._output_dir     = output_dir
        self._existing       = existing
        self._scanner        = FolderScanner(
            thumbnail_size=thumb_size,
            thumbnail_cache_dir=thumb_dir,
        )
        self._default_preset = default_preset

    def run(self) -> None:
        try:
            result = self._scanner.scan(
                input_dir=self._input_dir,
                output_dir=self._output_dir,
                existing_records=self._existing,
                progress_cb=lambda p, t, f: self.progress.emit(p, t, f),
                default_preset=self._default_preset,
            )
            self.scan_complete.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Queue item widget
# ─────────────────────────────────────────────────────────────────────────────

class QueueItemWidget(QWidget):
    """
    One row in the image queue list.

    Shows thumbnail · filename + meta · status badge · preset label.
    """

    _THUMB_W = 56
    _THUMB_H = 40

    def __init__(self, record: ImageRecord, parent=None) -> None:
        super().__init__(parent)
        self.record = record
        self.setFixedHeight(54)

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 8, 4)
        root.setSpacing(10)

        # ── Thumbnail ──────────────────────────────────────────────────────
        self._thumb = QLabel()
        self._thumb.setFixedSize(self._THUMB_W, self._THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(
            f"background: {PALETTE['surface_raised']}; border: 1px solid {PALETTE['border']}; "
            f"border-radius: 4px; padding: 1px;"
        )
        self._load_thumb()
        root.addWidget(self._thumb, alignment=Qt.AlignmentFlag.AlignVCenter)

        # ── Info column ────────────────────────────────────────────────────
        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(record.filename)
        self._name_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {PALETTE['text_primary']}; "
            f"background: transparent; border: none;"
        )
        self._name_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        meta = self._meta_text()
        self._meta_lbl = QLabel(meta)
        self._meta_lbl.setStyleSheet(
            f"font-size: 10px; color: {PALETTE['text_muted']}; "
            f"background: transparent; border: none;"
        )

        info.addWidget(self._name_lbl)
        info.addWidget(self._meta_lbl)
        root.addLayout(info, stretch=1)

        # ── Right column: badge + preset ───────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(3)
        right.setContentsMargins(0, 0, 0, 0)
        right.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._badge = StatusBadge(record.status.value)
        right.addWidget(self._badge, alignment=Qt.AlignmentFlag.AlignRight)

        preset_lbl = QLabel(f"Preset {record.preset_id}")
        preset_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        preset_lbl.setStyleSheet(
            f"font-size: 10px; color: {PALETTE['text_muted']}; "
            f"background: transparent; border: none;"
        )
        right.addWidget(preset_lbl)
        root.addLayout(right)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _meta_text(self) -> str:
        parts = []
        r = self.record
        if r.width and r.height:
            parts.append(f"{r.width}×{r.height}")
        if r.file_size:
            parts.append(human_readable_size(r.file_size))
        if r.format:
            parts.append(r.format)
        return "  ·  ".join(parts) if parts else "—"

    def update_status(self, status: str) -> None:
        self._badge.set_status(status)

    def _load_thumb(self) -> None:
        r = self.record
        pix: Optional[QPixmap] = None
        if r.thumbnail_path and Path(r.thumbnail_path).exists():
            pix = QPixmap(r.thumbnail_path)
        elif r.source_path and Path(r.source_path).exists():
            pix = QPixmap(r.source_path)

        if pix and not pix.isNull():
            pix = pix.scaled(
                self._THUMB_W, self._THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumb.setPixmap(pix)
        else:
            self._thumb.setPixmap(get_pixmap("image", color=PALETTE["text_muted"], size=22))


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(
        self,
        settings: SettingsManager,
        region_mgr: RegionConfigManager,
        project_dir: Path,
    ) -> None:
        super().__init__()
        self._settings    = settings
        self._region_mgr  = region_mgr
        self._project_dir = project_dir
        self._thumb_dir   = project_dir / ".thumbcache"

        # Runtime state
        self._records: list[ImageRecord]        = []
        self._record_map: dict[str, ImageRecord] = {}
        self._session: Optional[SessionManager] = None
        self._scan_worker: Optional[ScanWorker] = None
        self._batch_worker: Optional[BatchWorker] = None
        self._total_for_batch: int = 0
        self._completed: int = 0
        self._failed: int = 0

        # Scan progress animation timer
        self._scan_dot_timer = QTimer(self)
        self._scan_dot_timer.timeout.connect(self._tick_scan_dots)
        self._scan_dots = 0

        # Clean up any leftover thumbnail cache from previous runs to prevent disk bloat
        cleanup_thumbnail_cache(self._thumb_dir)

        self._build_ui()
        self._restore_session_folders()
        self._check_interrupted_session()

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_ui(self) -> None:
        self.setWindowTitle("Flow Image Manager")
        self.setMinimumSize(1080, 680)
        self.resize(1340, 820)

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addLayout(self._build_folder_row())
        root.addWidget(self._build_stats_row())
        root.addWidget(self._build_workspace(), stretch=1)
        root.addWidget(self._build_controls())
        root.addWidget(self._build_progress())

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_icon = QLabel("●")
        self._status_icon.setFixedWidth(14)
        self._status_icon.setStyleSheet(
            f"color: {PALETTE['success']}; font-size: 8px; background: transparent;"
        )
        self._status_lbl = QLabel("Ready")
        self._statusbar.addWidget(self._status_icon)
        self._statusbar.addWidget(self._status_lbl, 1)

    # ── Header ───────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setProperty("class", "surface")
        header.setFixedHeight(60)

        header.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['surface']};
                border: 1px solid {PALETTE['border']};
                border-radius: 9px;
                border-left: 4px solid {PALETTE['accent']};
            }}
        """)

        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(0)

        name_col = QVBoxLayout()
        name_col.setSpacing(1)
        name_col.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel("Flow Image Manager")
        name_lbl.setFont(QFont("Segoe UI Variable Text", 15, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            f"color: {PALETTE['text_primary']}; background: transparent; border: none;"
        )

        sub_lbl = QLabel("Manage and process scene images in batches")
        sub_lbl.setStyleSheet(
            f"color: {PALETTE['text_secondary']}; font-size: 11px; "
            f"background: transparent; border: none;"
        )

        name_col.addStretch()
        name_col.addWidget(name_lbl)
        name_col.addWidget(sub_lbl)
        name_col.addStretch()
        lay.addLayout(name_col)

        lay.addStretch()

        # Engine status chip
        self._engine_chip = QFrame()
        self._engine_chip.setStyleSheet(f"""
            QFrame {{
                background: {PALETTE['surface_raised']};
                border: 1px solid {PALETTE['border']};
                border-radius: 6px;
            }}
        """)
        chip_lay = QHBoxLayout(self._engine_chip)
        chip_lay.setContentsMargins(10, 4, 10, 4)
        chip_lay.setSpacing(6)

        self._engine_dot = QLabel("●")
        self._engine_dot.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 8px; "
            f"background: transparent; border: none;"
        )
        self._engine_lbl = QLabel("Checking engine…")
        self._engine_lbl.setStyleSheet(
            f"color: {PALETTE['text_secondary']}; font-size: 11px; font-weight: 500; "
            f"background: transparent; border: none;"
        )
        chip_lay.addWidget(self._engine_dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        chip_lay.addWidget(self._engine_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._engine_chip.setVisible(False)

        lay.addWidget(self._engine_chip)
        lay.addSpacing(12)

        # Settings button
        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setIcon(get_icon("settings", color=PALETTE["text_primary"], size=15))
        self._settings_btn.setFixedHeight(32)
        self._settings_btn.setMinimumWidth(92)
        self._settings_btn.setToolTip("Open application settings")
        self._settings_btn.clicked.connect(self._on_settings)
        lay.addWidget(self._settings_btn)

        lay.addSpacing(6)

        # Logs button
        self._logs_btn = QPushButton("Logs")
        self._logs_btn.setIcon(get_icon("folder", color=PALETTE["text_primary"], size=15))
        self._logs_btn.setFixedHeight(32)
        self._logs_btn.setMinimumWidth(76)
        self._logs_btn.setToolTip("Open logs directory in Explorer")
        self._logs_btn.clicked.connect(self._on_open_logs)
        lay.addWidget(self._logs_btn)

        self._update_engine_status()
        return header

    # ── Folder row ───────────────────────────────────────────────────────────

    def _build_folder_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._input_selector = FolderSelector(
            "Input Folder",
            action_label="Scan Images",
            action_icon="refresh",
        )
        self._input_selector.folder_changed.connect(self._on_input_folder_changed)
        self._input_selector.action_clicked.connect(self._on_scan)
        row.addWidget(self._input_selector)

        self._output_selector = FolderSelector("Output Folder")
        self._output_selector.folder_changed.connect(self._on_output_folder_changed)
        row.addWidget(self._output_selector)

        return row

    # ── Stats row ────────────────────────────────────────────────────────────

    def _build_stats_row(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._stat_total     = StatCard("Total Images", kind="total")
        self._stat_completed = StatCard("Completed",    kind="completed")
        self._stat_failed    = StatCard("Failed",       kind="failed")
        self._stat_remaining = StatCard("Remaining",    kind="remaining")

        for card in (
            self._stat_total, self._stat_completed,
            self._stat_failed, self._stat_remaining,
        ):
            lay.addWidget(card)

        return w

    # ── Workspace splitter ───────────────────────────────────────────────────

    def _build_workspace(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel: Queue ─────────────────────────────────────────────
        left_frame = QFrame()
        left_frame.setProperty("class", "surface")
        left_lay = QVBoxLayout(left_frame)
        left_lay.setContentsMargins(10, 10, 10, 10)
        left_lay.setSpacing(8)

        # Queue header
        q_hdr = QHBoxLayout()
        q_hdr.setContentsMargins(0, 0, 0, 0)
        q_hdr.addWidget(SectionHeader("Image Queue"))
        q_hdr.addStretch()

        preset_lbl = QLabel("Preset Override:")
        preset_lbl.setStyleSheet(f"font-size: 11px; color: {PALETTE['text_muted']}; font-weight: 500;")
        q_hdr.addWidget(preset_lbl)

        self._preset_override_combo = QComboBox()
        self._preset_override_combo.addItem("Default (per image)", "")
        self._preset_override_combo.addItem("Force Preset A", "A")
        self._preset_override_combo.addItem("Force Preset B", "B")
        self._preset_override_combo.setMinimumWidth(150)
        self._preset_override_combo.setFixedHeight(28)
        self._preset_override_combo.setToolTip("Override the preset assigned to all Ready/Pending images")
        self._preset_override_combo.currentIndexChanged.connect(self._on_preset_override_changed)
        q_hdr.addWidget(self._preset_override_combo)
        left_lay.addLayout(q_hdr)

        # Queue list
        self._queue_list = QListWidget()
        self._queue_list.setSpacing(1)
        self._queue_list.setUniformItemSizes(True)
        self._queue_list.currentItemChanged.connect(self._on_queue_selection)
        left_lay.addWidget(self._queue_list)

        # Empty state (shown when list is empty)
        self._empty_widget = self._build_empty_state()
        left_lay.addWidget(self._empty_widget)
        self._toggle_empty(True)

        splitter.addWidget(left_frame)

        # ── Right panel: Preview ──────────────────────────────────────────
        right_frame = QFrame()
        right_frame.setProperty("class", "surface")
        right_lay = QVBoxLayout(right_frame)
        right_lay.setContentsMargins(10, 10, 10, 10)
        right_lay.setSpacing(8)

        # Preview header row
        prev_hdr = QHBoxLayout()
        prev_hdr.setContentsMargins(0, 0, 0, 0)
        prev_hdr.addWidget(SectionHeader("Preview"))
        prev_hdr.addStretch()

        # Zoom controls
        for icon_name, tip, slot in [
            ("zoom-out", "Zoom out  (mouse wheel down)", self._preview_zoom_out),
            ("zoom-in",  "Zoom in  (mouse wheel up)",    self._preview_zoom_in),
            ("fit",      "Fit image to window",         self._preview_fit),
        ]:
            btn = QPushButton()
            btn.setIcon(get_icon(icon_name, color=PALETTE["text_secondary"], size=15))
            btn.setFixedSize(28, 28)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            prev_hdr.addWidget(btn)

        prev_hdr.addSpacing(6)

        self._region_btn = QPushButton(" Overlays")
        self._region_btn.setIcon(get_icon("layers", color=PALETTE["accent_light"], size=14))
        self._region_btn.setFixedHeight(28)
        self._region_btn.setCheckable(True)
        self._region_btn.setChecked(True)
        self._region_btn.setToolTip("Toggle region overlay rectangles")
        self._region_btn.clicked.connect(self._on_toggle_regions)
        prev_hdr.addWidget(self._region_btn)

        right_lay.addLayout(prev_hdr)

        # Image view
        self._preview = ImagePreviewWidget()
        right_lay.addWidget(self._preview, stretch=1)

        # Info bar below preview
        self._info_bar = self._build_info_bar()
        right_lay.addWidget(self._info_bar)

        # Review action bar (conditionally visible)
        self._review_bar = self._build_review_bar()
        self._review_bar.setVisible(False)
        right_lay.addWidget(self._review_bar)

        splitter.addWidget(right_frame)
        splitter.setSizes([420, 700])
        return splitter

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(8)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(get_pixmap("image", color=PALETTE["text_muted"], size=42))

        msg = QLabel("No images in queue")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {PALETTE['text_secondary']}; "
            f"background: transparent; border: none;"
        )

        hint = QLabel("Select an input folder above and click 'Scan Images'")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"font-size: 11px; color: {PALETTE['text_muted']}; "
            f"background: transparent; border: none;"
        )

        lay.addWidget(icon)
        lay.addWidget(msg)
        lay.addWidget(hint)
        return w

    def _build_info_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background: {PALETTE['surface_raised']};
                border: 1px solid {PALETTE['border']};
                border-radius: 6px;
            }}
        """)
        bar.setFixedHeight(30)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)

        self._info_filename = QLabel("—")
        self._info_filename.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-size: 11px; font-weight: 600; "
            f"background: transparent; border: none;"
        )

        self._info_meta = QLabel("")
        self._info_meta.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        self._info_meta.setAlignment(Qt.AlignmentFlag.AlignRight)

        lay.addWidget(self._info_filename, stretch=1)
        lay.addWidget(self._info_meta)
        return bar

    def _build_review_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background: rgba(253, 203, 110, 0.12);
                border: 1px solid rgba(253, 203, 110, 0.35);
                border-radius: 7px;
            }}
        """)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(8)

        lbl = QLabel("Manual review required:")
        lbl.setStyleSheet(
            f"font-weight: 600; font-size: 11px; color: {PALETTE['warning']}; "
            f"background: transparent; border: none;"
        )
        lay.addWidget(lbl)
        lay.addStretch()

        self._approve_btn = QPushButton("Approve")
        self._approve_btn.setIcon(get_icon("check", color="#ffffff", size=13))
        self._approve_btn.setProperty("primary", "true")
        self._approve_btn.setFixedHeight(28)
        self._approve_btn.clicked.connect(lambda: self._on_review_action("approved"))

        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setIcon(get_icon("x", color=PALETTE["error"], size=13))
        self._reject_btn.setProperty("danger", "true")
        self._reject_btn.setFixedHeight(28)
        self._reject_btn.clicked.connect(lambda: self._on_review_action("rejected"))

        self._skip_review_btn = QPushButton("Skip")
        self._skip_review_btn.setFixedHeight(28)
        self._skip_review_btn.clicked.connect(lambda: self._on_review_action("skipped"))

        lay.addWidget(self._approve_btn)
        lay.addWidget(self._reject_btn)
        lay.addWidget(self._skip_review_btn)
        return bar

    # ── Controls bar ─────────────────────────────────────────────────────────

    def _build_controls(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("class", "surface")
        bar.setFixedHeight(48)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(6)

        # Primary: Start Batch
        self._start_btn = QPushButton("Start Batch")
        self._start_btn.setIcon(get_icon("play", color="#ffffff", size=14))
        self._start_btn.setProperty("primary", "true")
        self._start_btn.setFixedHeight(32)
        self._start_btn.setMinimumWidth(116)
        self._start_btn.setEnabled(False)
        self._start_btn.setToolTip("Begin processing all Ready images")
        self._start_btn.clicked.connect(self._on_start_batch)
        lay.addWidget(self._start_btn)

        lay.addWidget(self._vline())

        # Pause / Resume / Stop
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setIcon(get_icon("pause", color=PALETTE["text_primary"], size=14))
        self._pause_btn.setFixedHeight(32)
        self._pause_btn.setEnabled(False)
        self._pause_btn.setToolTip("Pause after current image finishes")
        self._pause_btn.clicked.connect(self._on_pause)

        self._resume_btn = QPushButton("Resume")
        self._resume_btn.setIcon(get_icon("play", color=PALETTE["text_primary"], size=14))
        self._resume_btn.setFixedHeight(32)
        self._resume_btn.setEnabled(False)
        self._resume_btn.setToolTip("Resume paused batch")
        self._resume_btn.clicked.connect(self._on_resume)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setIcon(get_icon("stop", color=PALETTE["error"], size=14))
        self._stop_btn.setFixedHeight(32)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setProperty("danger", "true")
        self._stop_btn.setToolTip("Stop batch safely after current image finishes")
        self._stop_btn.clicked.connect(self._on_stop)

        for btn in (self._pause_btn, self._resume_btn, self._stop_btn):
            lay.addWidget(btn)

        lay.addWidget(self._vline())

        # Retry Failed
        self._retry_btn = QPushButton("Retry Failed")
        self._retry_btn.setIcon(get_icon("refresh", color=PALETTE["text_primary"], size=13))
        self._retry_btn.setFixedHeight(32)
        self._retry_btn.setEnabled(False)
        self._retry_btn.setToolTip("Reset all Failed images back to Ready")
        self._retry_btn.clicked.connect(self._on_retry_failed)
        lay.addWidget(self._retry_btn)

        lay.addStretch()

        # Clear session
        self._clear_btn = QPushButton("Clear Session")
        self._clear_btn.setIcon(get_icon("trash", color=PALETTE["text_muted"], size=14))
        self._clear_btn.setFixedHeight(32)
        self._clear_btn.setEnabled(False)
        self._clear_btn.setToolTip("Remove all records from current session (source images and output files are preserved)")
        self._clear_btn.clicked.connect(self._on_clear_session)
        lay.addWidget(self._clear_btn)

        return bar

    def _build_progress(self) -> ProgressSection:
        self._progress = ProgressSection()
        return self._progress

    @staticmethod
    def _vline() -> QFrame:
        """A thin vertical separator for the controls bar."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        line.setStyleSheet(
            f"background: {PALETTE['border']}; border: none; margin: 4px 3px;"
        )
        return line

    # =========================================================================
    # Startup helpers
    # =========================================================================

    def _restore_session_folders(self) -> None:
        inp = self._settings.input_folder
        out = self._settings.output_folder
        if inp:
            self._input_selector.set_path(inp)
        if out:
            self._output_selector.set_path(out)

    def _check_interrupted_session(self) -> None:
        out = self._settings.output_folder
        if not out:
            return
        db_path = Path(out) / "flow_session.db"
        if not db_path.exists():
            return
        session = SessionManager(db_path)
        if session.has_interrupted_session():
            reply = QMessageBox.question(
                self, "Resume Session",
                "An unfinished processing session was detected.\n\n"
                "Would you like to resume it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                session.reset_processing_to_ready()
                self._session = session
                self._load_records(session.load_all_records())
                self._set_status("Session resumed.", "success")
            else:
                session.close()
        else:
            session.close()

    # =========================================================================
    # Folder handlers
    # =========================================================================

    def _on_input_folder_changed(self, path: str) -> None:
        self._settings.input_folder = path
        self._settings.save()
        self._set_status(f"Input: {path}", "info")

    def _on_output_folder_changed(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            reply = QMessageBox.question(
                self, "Create Folder?",
                f"The output folder does not exist:\n{path}\n\nCreate it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    ensure_dir(p)
                except Exception as exc:
                    QMessageBox.critical(self, "Error", f"Cannot create folder:\n{exc}")
                    return
            else:
                return
        self._settings.output_folder = path
        self._settings.save()
        self._set_status(f"Output: {path}", "info")

    # =========================================================================
    # Scanning
    # =========================================================================

    def _on_scan(self) -> None:
        inp = self._input_selector.get_path()
        if not inp or not Path(inp).is_dir():
            QMessageBox.warning(
                self, "No Input Folder",
                "Please select a valid input folder first."
            )
            return

        out = self._output_selector.get_path() or None

        self._input_selector.set_action_enabled(False)
        self._scan_dots = 0
        self._scan_dot_timer.start(400)
        self._set_status("Scanning…", "info")

        existing = {r.source_path: r for r in self._records}

        self._scan_worker = ScanWorker(
            input_dir=Path(inp),
            output_dir=Path(out) if out else None,
            existing=existing,
            thumb_dir=self._thumb_dir,
            thumb_size=self._settings.thumbnail_size,
            default_preset=self._settings.default_preset,
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.scan_complete.connect(self._on_scan_complete)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _tick_scan_dots(self) -> None:
        dots = "." * ((self._scan_dots % 3) + 1)
        self._set_status(f"Scanning{dots}", "info")
        self._scan_dots += 1

    def _on_scan_progress(self, processed: int, total: int, filename: str) -> None:
        self._set_status(f"Scanning {processed}/{total} — {filename}", "info")

    def _on_scan_complete(self, result: ScanResult) -> None:
        self._scan_dot_timer.stop()
        self._input_selector.set_action_enabled(True)

        self._load_records(result.records)

        out = self._output_selector.get_path()
        if out:
            db_path = Path(out) / "flow_session.db"
            self._session = SessionManager(db_path)
            self._session.save_records(result.records)

        msg = (
            f"Scan complete — {result.total_valid} valid, "
            f"{result.total_skipped} skipped  ({result.scan_duration_s:.1f}s)"
        )
        self._set_status(msg, "success")
        log.info(msg)

        if result.warnings:
            for w in result.warnings:
                log.warning(w)
            QMessageBox.information(
                self, "Scan Warnings",
                "\n".join(result.warnings[:5])
                + ("\n…" if len(result.warnings) > 5 else ""),
            )

    def _on_scan_error(self, error: str) -> None:
        self._scan_dot_timer.stop()
        self._input_selector.set_action_enabled(True)
        self._set_status(f"Scan failed: {error}", "error")
        QMessageBox.critical(self, "Scan Error", error)

    # =========================================================================
    # Queue management
    # =========================================================================

    def _load_records(self, records: list[ImageRecord]) -> None:
        self._records    = list(records)
        self._record_map = {r.source_path: r for r in records}
        self._rebuild_queue()
        self._update_stats()
        self._update_controls()

    def _rebuild_queue(self) -> None:
        self._queue_list.clear()
        for record in self._records:
            item = QListWidgetItem()
            widget = QueueItemWidget(record)
            item.setSizeHint(QSize(0, 54))
            item.setData(Qt.ItemDataRole.UserRole, record.source_path)
            self._queue_list.addItem(item)
            self._queue_list.setItemWidget(item, widget)
        self._toggle_empty(len(self._records) == 0)

    def _toggle_empty(self, empty: bool) -> None:
        self._queue_list.setVisible(not empty)
        self._empty_widget.setVisible(empty)

    def _update_queue_item(self, source_path: str) -> None:
        record = self._record_map.get(source_path)
        if not record:
            return
        for i in range(self._queue_list.count()):
            item = self._queue_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == source_path:
                w = self._queue_list.itemWidget(item)
                if w:
                    w.update_status(record.status.value)
                break

    def _on_queue_selection(
        self, current: QListWidgetItem, _previous: QListWidgetItem
    ) -> None:
        if current is None:
            self._preview.clear()
            self._info_filename.setText("—")
            self._info_meta.setText("")
            self._review_bar.setVisible(False)
            return

        source_path = current.data(Qt.ItemDataRole.UserRole)
        record = self._record_map.get(source_path)
        if not record:
            return

        # Preview
        p = Path(record.source_path)
        if p.exists():
            self._preview.load_image(p)
        else:
            self._preview.clear()

        # Region overlay
        preset = self._region_mgr.get_preset(record.preset_id)
        self._preview.set_regions(preset.regions if preset else [])

        # Info bar
        self._info_filename.setText(record.filename)
        meta_parts = []
        if record.width and record.height:
            meta_parts.append(f"{record.width} × {record.height}")
        if record.format:
            meta_parts.append(record.format)
        if record.file_size:
            meta_parts.append(human_readable_size(record.file_size))
        meta_parts.append(f"Preset {record.preset_id}")
        self._info_meta.setText("  ·  ".join(meta_parts))

        # Review bar
        self._review_bar.setVisible(record.status == ImageStatus.NEEDS_REVIEW)

    def _on_preset_override_changed(self, _: int) -> None:
        override = self._preset_override_combo.currentData()
        if not override:
            return
        for r in self._records:
            if r.status in (ImageStatus.READY, ImageStatus.PENDING):
                r.preset_id = override
        if self._session:
            self._session.save_records(self._records)
        self._rebuild_queue()

    # ── Zoom / region toggle helpers ─────────────────────────────────────────

    def _preview_zoom_in(self)  -> None: self._preview.zoom_in()
    def _preview_zoom_out(self) -> None: self._preview.zoom_out()
    def _preview_fit(self)      -> None: self._preview.zoom_reset()

    def _on_toggle_regions(self) -> None:
        on = self._region_btn.isChecked()
        self._preview.set_show_regions(on)

    # =========================================================================
    # Stats
    # =========================================================================

    def _update_stats(self) -> None:
        total     = len(self._records)
        completed = sum(1 for r in self._records if r.status == ImageStatus.COMPLETED)
        failed    = sum(1 for r in self._records if r.status == ImageStatus.FAILED)
        remaining = max(0, total - completed - failed)

        self._stat_total.set_value(total)
        self._stat_completed.set_value(completed)
        self._stat_failed.set_value(failed)
        self._stat_remaining.set_value(remaining)

    # =========================================================================
    # Batch controls
    # =========================================================================

    def _on_start_batch(self) -> None:
        out_str = self._output_selector.get_path()
        if not out_str:
            QMessageBox.warning(
                self, "No Output Folder",
                "Please select an output folder before starting."
            )
            return

        out = Path(out_str)
        ensure_dir(out)

        if self._session is None:
            self._session = SessionManager(out / "flow_session.db")

        eligible = [
            r for r in self._records
            if r.status in (ImageStatus.READY, ImageStatus.PENDING)
        ]
        if not eligible:
            QMessageBox.information(
                self, "Nothing to Process",
                "No images have Ready or Pending status."
            )
            return

        try:
            engine = get_default_engine()
        except RuntimeError as exc:
            QMessageBox.critical(self, "Engine Error", str(exc))
            return

        self._batch_worker = BatchWorker(
            records=eligible,
            output_dir=out,
            engine=engine,
            session=self._session,
            region_mgr=self._region_mgr,
            conflict_mode=self._settings.conflict_mode,
            retry_limit=self._settings.retry_limit,
            require_review=self._settings.require_manual_review,
        )
        self._batch_worker.progress_updated.connect(self._on_batch_progress)
        self._batch_worker.image_processed.connect(self._on_image_processed)
        self._batch_worker.batch_finished.connect(self._on_batch_finished)
        self._batch_worker.log_message.connect(self._on_batch_log)
        self._batch_worker.review_required.connect(self._on_review_required)

        self._total_for_batch = len(eligible)
        self._completed = self._failed = 0
        self._progress.reset()

        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._resume_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)

        self._batch_worker.start()
        self._set_status(f"Processing {len(eligible)} image(s)…", "info")
        log.info("Batch started: %d images.", len(eligible))

    def _on_pause(self) -> None:
        if self._batch_worker:
            self._batch_worker.pause()
            self._pause_btn.setEnabled(False)
            self._resume_btn.setEnabled(True)
            self._set_status("Paused — click Resume to continue.", "warning")

    def _on_resume(self) -> None:
        if self._batch_worker:
            self._batch_worker.resume()
            self._pause_btn.setEnabled(True)
            self._resume_btn.setEnabled(False)
            self._set_status("Resumed.", "info")

    def _on_stop(self) -> None:
        if self._batch_worker:
            self._batch_worker.stop()
            self._stop_btn.setEnabled(False)
            self._set_status("Stopping after current image…", "warning")

    def _on_retry_failed(self) -> None:
        if self._session:
            n = self._session.reset_failed_to_ready()
            self._load_records(self._session.load_all_records())
            self._set_status(f"Reset {n} failed image(s) to Ready.", "success")

    def _on_clear_session(self) -> None:
        reply = QMessageBox.question(
            self, "Clear Session",
            "Clear all processing records and cache?\n\n"
            "Source images, output files, folder settings, and preset configurations will NOT be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._session:
                self._session.clear_all_records()
            self._records    = []
            self._record_map = {}
            # Clear thumbnail cache to prevent disk bloating
            out_str = self._output_selector.get_path()
            out_dir = Path(out_str) if out_str else None
            cleanup_session_cache(self._thumb_dir, out_dir)
            self._rebuild_queue()
            self._update_stats()
            self._progress.reset()
            self._update_controls()
            self._set_status("Session and cache cleared.", "success")

    # ── Batch callbacks ───────────────────────────────────────────────────────

    def _on_batch_progress(
        self, completed: int, failed: int, remaining: int,
        current_file: str, elapsed_s: float,
    ) -> None:
        self._completed = completed
        self._failed    = failed
        self._progress.update_progress(
            completed, failed, remaining,
            self._total_for_batch, current_file, elapsed_s,
        )
        self._update_stats()

    def _on_image_processed(
        self, source_path: str, status: str, output_path: str, error: str
    ) -> None:
        record = self._record_map.get(source_path)
        if record:
            record.status = ImageStatus(status)
            if output_path:
                record.output_path = output_path
            if error:
                record.last_error = error
        self._update_queue_item(source_path)
        self._update_stats()

    def _on_batch_finished(
        self, completed: int, failed: int, duration_s: float
    ) -> None:
        m, s = divmod(int(duration_s), 60)
        time_str = f"{m}m {s}s" if m else f"{s}s"
        msg = f"Done — {completed} completed, {failed} failed  ({time_str})"
        self._set_status(msg, "success" if failed == 0 else "warning")
        log.info(msg)

        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._retry_btn.setEnabled(failed > 0)
        self._clear_btn.setEnabled(True)

        if failed > 0:
            QMessageBox.information(
                self, "Batch Complete",
                f"{completed} image(s) processed successfully.\n"
                f"{failed} image(s) failed.\n\n"
                f"Use 'Retry Failed' to reprocess.",
            )

    def _on_batch_log(self, level: str, message: str) -> None:
        kind = "warning" if level == "WARNING" else "error" if level == "ERROR" else "info"
        self._set_status(message, kind)

    def _on_review_required(self, source_path: str) -> None:
        record = self._record_map.get(source_path)
        if record:
            record.status = ImageStatus.NEEDS_REVIEW
            self._update_queue_item(source_path)
        self._set_status(
            f"Review required: {Path(source_path).name}", "warning"
        )

    # ── Review actions ────────────────────────────────────────────────────────

    def _on_review_action(self, action: str) -> None:
        item = self._queue_list.currentItem()
        if not item:
            return
        record = self._record_map.get(item.data(Qt.ItemDataRole.UserRole))
        if not record:
            return

        from app.models.image_record import ReviewStatus
        record.review_status = ReviewStatus(action)
        record.status = (
            ImageStatus.READY if action == "approved" else ImageStatus.SKIPPED
        )
        if self._session:
            self._session.save_record(record)
        self._update_queue_item(record.source_path)
        self._review_bar.setVisible(False)
        self._update_stats()

    # =========================================================================
    # Settings / logs
    # =========================================================================

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self._settings, self._region_mgr, self)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self) -> None:
        self._update_engine_status()
        item = self._queue_list.currentItem()
        if item:
            self._on_queue_selection(item, None)
        self._set_status("Settings saved.", "success")

    def _on_open_logs(self) -> None:
        log_dir = get_log_dir()
        if log_dir and log_dir.exists():
            os.startfile(str(log_dir))
        else:
            QMessageBox.information(self, "Logs", "Log directory not found.")

    # =========================================================================
    # Control state + engine status
    # =========================================================================

    def _update_controls(self) -> None:
        has_records = bool(self._records)
        has_ready   = any(
            r.status in (ImageStatus.READY, ImageStatus.PENDING)
            for r in self._records
        )
        has_failed  = any(r.status == ImageStatus.FAILED for r in self._records)
        running     = (
            self._batch_worker is not None and self._batch_worker.isRunning()
        )

        self._start_btn.setEnabled(has_ready and not running)
        self._pause_btn.setEnabled(running)
        self._resume_btn.setEnabled(False)
        self._stop_btn.setEnabled(running)
        self._retry_btn.setEnabled(has_failed and not running)
        self._clear_btn.setEnabled(has_records and not running)

    def _update_engine_status(self) -> None:
        engines = list_engines()
        if not engines:
            return

        name, available, _ = engines[0]
        if available:
            self._engine_dot.setStyleSheet(
                f"color: {PALETTE['success']}; font-size: 8px; "
                f"background: transparent; border: none;"
            )
            self._engine_lbl.setText(name)
        else:
            self._engine_dot.setStyleSheet(
                f"color: {PALETTE['error']}; font-size: 8px; "
                f"background: transparent; border: none;"
            )
            self._engine_lbl.setText(f"{name} (unavailable)")

        self._engine_chip.setVisible(True)

    # =========================================================================
    # Status bar
    # =========================================================================

    def _set_status(self, msg: str, kind: str = "info") -> None:
        """Update status bar text with an optional semantic color dot."""
        color_map = {
            "success": PALETTE["success"],
            "warning": PALETTE["warning"],
            "error":   PALETTE["error"],
            "info":    PALETTE["text_secondary"],
        }
        color = color_map.get(kind, PALETTE["text_secondary"])
        self._status_icon.setStyleSheet(
            f"color: {color}; font-size: 8px; background: transparent;"
        )
        self._status_lbl.setText(msg)

    # =========================================================================
    # Close event
    # =========================================================================

    def closeEvent(self, event) -> None:
        if self._batch_worker and self._batch_worker.isRunning():
            reply = QMessageBox.question(
                self, "Exit",
                "Batch processing is running.\n\nStop and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._batch_worker.stop()
            self._batch_worker.wait(3000)

        self._scan_dot_timer.stop()
        if self._session:
            self._session.close()

        # Reclaim disk space by clearing thumbnail cache and orphaned temp files on exit
        out_str = self._output_selector.get_path()
        out_dir = Path(out_str) if out_str else None
        cleanup_session_cache(self._thumb_dir, out_dir)

        # Retain folder locations, preferences, and preset references
        self._settings.save()
        event.accept()
