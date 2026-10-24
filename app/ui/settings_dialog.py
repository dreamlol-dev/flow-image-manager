"""
settings_dialog.py — Application settings and region-configuration dialog.

Two tabs:
  1. General Settings — folders, presets, processing options, logging
  2. Region Presets — interactive region editor with image overlay

The region editor lets the user:
  - Pick a preset (A or B).
  - Load a reference image.
  - Drag rectangle handles to reposition / resize each region.
  - Save the configuration.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QRectF, QPointF, Signal, QSizeF, QPoint
)
from PySide6.QtGui import (
    QColor, QMouseEvent, QPainter, QPen, QBrush, QImage, QPixmap, QFont,
    QPaintEvent
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget, QFrame, QSizePolicy
)

from app.core.region_config import (
    LayoutPreset, NormalizedRegion, RegionConfigManager
)
from app.core.settings_manager import SettingsManager
from app.ui.components import PALETTE, SectionHeader
from app.ui.icons import get_icon, get_pixmap


# ─────────────────────────────────────────────────────────────────────────────
# Interactive region editor canvas
# ─────────────────────────────────────────────────────────────────────────────

class RegionEditorCanvas(QWidget):
    """
    Canvas that displays a reference image and allows the user to
    drag-resize normalized region rectangles.

    Emits ``regions_changed(list[NormalizedRegion])`` on every edit.
    """

    regions_changed = Signal(list)  # list[NormalizedRegion]

    _HANDLE_SIZE = 9  # px
    _MIN_DIM = 0.01   # minimum normalized region dimension

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._pixmap: Optional[QPixmap] = None
        self._regions: list[NormalizedRegion] = []
        self._colors = [
            QColor(108, 92, 231),  # purple (#6c5ce7)
            QColor(0, 184, 148),   # emerald (#00b894)
        ]

        # Drag state
        self._drag_region_idx: int = -1
        self._drag_handle: str = ""   # "body", "nw","ne","sw","se"
        self._drag_start_pos: QPointF = QPointF()
        self._drag_start_region: Optional[NormalizedRegion] = None

    # ── Public API ──────────────────────────────────────────────────────────

    def load_reference(self, path: Path) -> bool:
        qimg = QImage(str(path))
        if qimg.isNull():
            return False
        self._pixmap = QPixmap.fromImage(qimg)
        self.update()
        return True

    def set_regions(self, regions: list[NormalizedRegion]) -> None:
        self._regions = [copy.deepcopy(r) for r in regions]
        self.update()

    def get_regions(self) -> list[NormalizedRegion]:
        return [copy.deepcopy(r) for r in self._regions]

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(PALETTE["bg"]))

        if self._pixmap is None or self._pixmap.isNull():
            # Empty state helper
            painter.setPen(QColor(PALETTE["text_muted"]))
            painter.setFont(QFont("Segoe UI Variable Text", 12))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Load a reference image to calibrate preset regions"
            )
            return

        # Scaled image centered
        img_rect = self._scaled_image_rect()
        painter.drawPixmap(img_rect.toRect(), self._pixmap)

        # Draw subtle outer border around image
        painter.setPen(QPen(QColor(PALETTE["border_light"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(img_rect)

        # Regions
        for i, region in enumerate(self._regions):
            color = self._colors[i % len(self._colors)]
            self._draw_region(painter, region, color, i)

    def _draw_region(
        self, painter: QPainter, region: NormalizedRegion,
        color: QColor, idx: int
    ) -> None:
        img_rect = self._scaled_image_rect()
        rx = img_rect.left() + region.x * img_rect.width()
        ry = img_rect.top() + region.y * img_rect.height()
        rw = region.width * img_rect.width()
        rh = region.height * img_rect.height()
        rect = QRectF(rx, ry, rw, rh)

        # Region fill
        fill = QColor(color)
        fill.setAlpha(45)
        painter.fillRect(rect, fill)

        # Region outline
        pen = QPen(color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Label badge (contrast-preserving pill)
        label_text = region.label or f"Region {idx + 1}"
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        text_w = painter.fontMetrics().horizontalAdvance(label_text) + 8
        text_h = 16
        pill_rect = QRectF(rx + 2, ry + 2, text_w, text_h)

        badge_bg = QColor(PALETTE["surface_raised"])
        badge_bg.setAlpha(220)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(badge_bg))
        painter.drawRoundedRect(pill_rect, 3, 3)

        painter.setPen(QPen(QColor(PALETTE["text_primary"])))
        painter.drawText(
            QRectF(rx + 6, ry + 3, text_w - 4, text_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label_text,
        )

        # Handles at corners (white border + color center)
        hs = self._HANDLE_SIZE
        half = hs / 2
        for hx, hy in [
            (rx - half, ry - half),
            (rx + rw - half, ry - half),
            (rx - half, ry + rh - half),
            (rx + rw - half, ry + rh - half),
        ]:
            handle_rect = QRectF(hx, hy, hs, hs)
            painter.setPen(QPen(QColor("#ffffff"), 1.2))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(handle_rect, 2, 2)

    # ── Mouse events ────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = QPointF(event.pos())
        self._drag_region_idx, self._drag_handle = self._hit_test(pos)
        if self._drag_region_idx >= 0:
            self._drag_start_pos = pos
            self._drag_start_region = copy.deepcopy(
                self._regions[self._drag_region_idx]
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = QPointF(event.pos())
        hit_idx, hit_handle = self._hit_test(pos)
        if hit_handle in ("nw", "se"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif hit_handle in ("ne", "sw"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif hit_handle == "body":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

        if self._drag_region_idx < 0:
            return

        img_rect = self._scaled_image_rect()
        if img_rect.width() <= 0 or img_rect.height() <= 0:
            return

        dx = (pos.x() - self._drag_start_pos.x()) / img_rect.width()
        dy = (pos.y() - self._drag_start_pos.y()) / img_rect.height()

        orig = self._drag_start_region
        region = self._regions[self._drag_region_idx]
        m = self._MIN_DIM

        if self._drag_handle == "body":
            region.x = max(0.0, min(1.0 - orig.width, orig.x + dx))
            region.y = max(0.0, min(1.0 - orig.height, orig.y + dy))

        elif self._drag_handle == "nw":
            new_x = max(0.0, orig.x + dx)
            new_y = max(0.0, orig.y + dy)
            new_w = orig.width - (new_x - orig.x)
            new_h = orig.height - (new_y - orig.y)
            if new_w >= m and new_h >= m:
                region.x = new_x
                region.y = new_y
                region.width = new_w
                region.height = new_h

        elif self._drag_handle == "ne":
            new_y = max(0.0, orig.y + dy)
            new_w = max(m, orig.width + dx)
            new_h = orig.height - (new_y - orig.y)
            if new_h >= m and orig.x + new_w <= 1.0:
                region.y = new_y
                region.width = new_w
                region.height = new_h

        elif self._drag_handle == "sw":
            new_x = max(0.0, orig.x + dx)
            new_w = orig.width - (new_x - orig.x)
            new_h = max(m, orig.height + dy)
            if new_w >= m and orig.y + new_h <= 1.0:
                region.x = new_x
                region.width = new_w
                region.height = new_h

        elif self._drag_handle == "se":
            new_w = max(m, orig.width + dx)
            new_h = max(m, orig.height + dy)
            if orig.x + new_w <= 1.0 and orig.y + new_h <= 1.0:
                region.width = new_w
                region.height = new_h

        self.update()
        self.regions_changed.emit(self.get_regions())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_region_idx = -1
        self._drag_handle = ""
        self._drag_start_region = None

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _scaled_image_rect(self) -> QRectF:
        if not self._pixmap or self._pixmap.isNull():
            return QRectF(self.rect())
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = self.width() - 20
        wh = self.height() - 20
        scale = min(ww / pw, wh / ph)
        sw = pw * scale
        sh = ph * scale
        ox = (self.width() - sw) / 2
        oy = (self.height() - sh) / 2
        return QRectF(ox, oy, sw, sh)

    def _hit_test(self, pos: QPointF) -> tuple[int, str]:
        """Return (region_idx, handle_name) or (-1, "")."""
        img_rect = self._scaled_image_rect()
        hs = self._HANDLE_SIZE + 4  # slightly larger hit area for ease of use
        half = hs / 2

        for i, region in enumerate(self._regions):
            rx = img_rect.left() + region.x * img_rect.width()
            ry = img_rect.top() + region.y * img_rect.height()
            rw = region.width * img_rect.width()
            rh = region.height * img_rect.height()

            handles = {
                "nw": QRectF(rx - half, ry - half, hs, hs),
                "ne": QRectF(rx + rw - half, ry - half, hs, hs),
                "sw": QRectF(rx - half, ry + rh - half, hs, hs),
                "se": QRectF(rx + rw - half, ry + rh - half, hs, hs),
            }
            for handle_name, handle_rect in handles.items():
                if handle_rect.contains(pos):
                    return i, handle_name

            body = QRectF(rx, ry, rw, rh)
            if body.contains(pos):
                return i, "body"

        return -1, ""


# ─────────────────────────────────────────────────────────────────────────────
# Settings Dialog
# ─────────────────────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """
    Main settings dialog with General and Region Presets tabs.
    """

    settings_saved = Signal()

    def __init__(
        self,
        settings: SettingsManager,
        region_mgr: RegionConfigManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — Flow Image Manager")
        self.setMinimumSize(860, 600)
        self.resize(920, 640)

        self._settings = settings
        self._region_mgr = region_mgr
        self._current_preset_id = "A"
        self._working_presets: dict[str, LayoutPreset] = {
            pid: copy.deepcopy(region_mgr.get_preset(pid))
            for pid in ("A", "B")
            if region_mgr.get_preset(pid)
        }

        self._build_ui()
        self._populate_values()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_region_tab(), "Region Presets")
        layout.addWidget(tabs, stretch=1)

        # Dialog buttons row
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 4, 0, 0)

        self._reset_all_btn = QPushButton("Reset to Defaults…")
        self._reset_all_btn.setIcon(get_icon("refresh", color=PALETTE["text_muted"], size=13))
        self._reset_all_btn.setFixedHeight(32)
        self._reset_all_btn.clicked.connect(self._on_reset)
        btn_bar.addWidget(self._reset_all_btn)

        btn_bar.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(32)
        self._cancel_btn.setMinimumWidth(80)
        self._cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save Settings")
        self._save_btn.setIcon(get_icon("check", color="#ffffff", size=14))
        self._save_btn.setProperty("primary", "true")
        self._save_btn.setFixedHeight(32)
        self._save_btn.setMinimumWidth(116)
        self._save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(self._save_btn)

        layout.addLayout(btn_bar)

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(14)

        # ── Processing group ───────────────────────────────────────────────
        proc_group = QGroupBox("Processing")
        proc_form = QFormLayout(proc_group)
        proc_form.setSpacing(10)
        proc_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._default_preset_combo = QComboBox()
        self._default_preset_combo.addItem("Preset A — Single Region", "A")
        self._default_preset_combo.addItem("Preset B — Double Region", "B")
        self._default_preset_combo.setFixedWidth(240)
        proc_form.addRow("Default Preset:", self._default_preset_combo)

        self._conflict_combo = QComboBox()
        self._conflict_combo.addItem("Generate unique filename (recommended)", "unique")
        self._conflict_combo.addItem("Skip existing outputs", "skip")
        self._conflict_combo.addItem("Ask each time", "ask")
        self._conflict_combo.setFixedWidth(240)
        proc_form.addRow("Filename Conflict:", self._conflict_combo)

        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(1, 10)
        self._retry_spin.setValue(2)
        self._retry_spin.setFixedWidth(80)
        proc_form.addRow("Retry Limit:", self._retry_spin)

        self._review_check = QCheckBox("Require manual review before processing images")
        proc_form.addRow("", self._review_check)

        layout.addWidget(proc_group)

        # ── Display group ──────────────────────────────────────────────────
        disp_group = QGroupBox("Display & Preview")
        disp_form = QFormLayout(disp_group)
        disp_form.setSpacing(10)
        disp_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._thumb_spin = QSpinBox()
        self._thumb_spin.setRange(64, 256)
        self._thumb_spin.setSingleStep(16)
        self._thumb_spin.setFixedWidth(80)
        disp_form.addRow("Thumbnail Size (px):", self._thumb_spin)

        self._fit_check = QCheckBox("Auto-fit image to preview panel on selection")
        disp_form.addRow("", self._fit_check)

        layout.addWidget(disp_group)

        # ── Logging group ──────────────────────────────────────────────────
        log_group = QGroupBox("Diagnostics & Logging")
        log_form = QFormLayout(log_group)
        log_form.setSpacing(10)
        log_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._log_combo = QComboBox()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self._log_combo.addItem(level)
        self._log_combo.setFixedWidth(140)
        log_form.addRow("Log Verbosity:", self._log_combo)

        layout.addWidget(log_group)
        layout.addStretch()
        return w

    def _build_region_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Top selector bar
        top_bar = QFrame()
        top_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['surface_raised']};
                border: 1px solid {PALETTE['border']};
                border-radius: 8px;
            }}
        """)
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(12, 6, 12, 6)
        top_lay.setSpacing(10)

        preset_lbl = QLabel("Calibrate Preset:")
        preset_lbl.setStyleSheet(f"font-weight: 600; color: {PALETTE['text_primary']};")
        top_lay.addWidget(preset_lbl)

        self._preset_combo = QComboBox()
        self._preset_combo.addItem("Preset A — Single Region", "A")
        self._preset_combo.addItem("Preset B — Double Region", "B")
        self._preset_combo.setFixedWidth(210)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        top_lay.addWidget(self._preset_combo)

        top_lay.addSpacing(10)

        load_ref_btn = QPushButton("Load Reference Image…")
        load_ref_btn.setIcon(get_icon("image", color=PALETTE["text_primary"], size=15))
        load_ref_btn.setFixedHeight(30)
        load_ref_btn.clicked.connect(self._on_load_reference)
        top_lay.addWidget(load_ref_btn)

        top_lay.addStretch()
        layout.addWidget(top_bar)

        # Canvas + coordinates panel splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Canvas with rounded border container
        canvas_container = QFrame()
        canvas_container.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['bg']};
                border: 1px solid {PALETTE['border']};
                border-radius: 8px;
            }}
        """)
        canvas_lay = QVBoxLayout(canvas_container)
        canvas_lay.setContentsMargins(4, 4, 4, 4)

        self._canvas = RegionEditorCanvas()
        self._canvas.regions_changed.connect(self._on_regions_changed)
        canvas_lay.addWidget(self._canvas)
        splitter.addWidget(canvas_container)

        # Right panel: coordinate controls
        right_panel = QFrame()
        right_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['surface_raised']};
                border: 1px solid {PALETTE['border']};
                border-radius: 8px;
            }}
        """)
        right_panel.setMaximumWidth(290)
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(12, 12, 12, 12)
        right_lay.setSpacing(10)

        right_lay.addWidget(SectionHeader("Normalized Bounds"))

        hint_lbl = QLabel("Values are 0.0 – 1.0 relative to image size.")
        hint_lbl.setStyleSheet(f"font-size: 11px; color: {PALETTE['text_muted']};")
        right_lay.addWidget(hint_lbl)

        self._region_panels: list[QGroupBox] = []
        self._region_spins: list[dict[str, QDoubleSpinBox]] = []

        labels_display = {"x": "X:", "y": "Y:", "width": "Width:", "height": "Height:"}

        for i in range(2):
            box = QGroupBox(f"Region {i + 1}")
            box_form = QFormLayout(box)
            box_form.setSpacing(6)
            box_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

            spins: dict[str, QDoubleSpinBox] = {}
            for field_name in ("x", "y", "width", "height"):
                spin = QDoubleSpinBox()
                spin.setRange(0.0, 1.0)
                spin.setSingleStep(0.005)
                spin.setDecimals(4)
                spin.setFixedHeight(26)
                spin.valueChanged.connect(self._on_spin_changed)
                spins[field_name] = spin
                box_form.addRow(labels_display[field_name], spin)

            right_lay.addWidget(box)
            self._region_panels.append(box)
            self._region_spins.append(spins)

        right_lay.addStretch()

        reset_btn = QPushButton("Reset Preset Defaults")
        reset_btn.setIcon(get_icon("refresh", color=PALETTE["text_muted"], size=13))
        reset_btn.setFixedHeight(30)
        reset_btn.setToolTip("Reset the selected preset to default coordinates")
        reset_btn.clicked.connect(self._on_reset_preset)
        right_lay.addWidget(reset_btn)

        splitter.addWidget(right_panel)
        splitter.setSizes([620, 270])
        layout.addWidget(splitter, stretch=1)

        return w

    # ── Population ───────────────────────────────────────────────────────────

    def _populate_values(self) -> None:
        s = self._settings
        idx = self._default_preset_combo.findData(s.default_preset)
        if idx >= 0:
            self._default_preset_combo.setCurrentIndex(idx)

        idx = self._conflict_combo.findData(s.conflict_mode)
        if idx >= 0:
            self._conflict_combo.setCurrentIndex(idx)

        self._retry_spin.setValue(s.retry_limit)
        self._review_check.setChecked(s.require_manual_review)
        self._thumb_spin.setValue(s.thumbnail_size)
        self._fit_check.setChecked(s.get("preview_zoom_fit_on_select", True))

        log_idx = self._log_combo.findText(s.log_verbosity)
        if log_idx >= 0:
            self._log_combo.setCurrentIndex(log_idx)

        self._load_preset_into_editor("A")

    def _load_preset_into_editor(self, preset_id: str) -> None:
        self._current_preset_id = preset_id
        preset = self._working_presets.get(preset_id)
        if not preset:
            return

        num_regions = len(preset.regions)
        for i, panel in enumerate(self._region_panels):
            panel.setVisible(i < num_regions)

        for i, region in enumerate(preset.regions):
            if i >= len(self._region_spins):
                break
            spins = self._region_spins[i]
            for field_name in ("x", "y", "width", "height"):
                spins[field_name].blockSignals(True)
                spins[field_name].setValue(getattr(region, field_name))
                spins[field_name].blockSignals(False)

        self._canvas.set_regions(preset.regions)

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_preset_changed(self, index: int) -> None:
        preset_id = self._preset_combo.itemData(index)
        self._load_preset_into_editor(preset_id)

    def _on_load_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Reference Image", "",
            "Images (*.jpg *.jpeg *.png *.webp)"
        )
        if path:
            if not self._canvas.load_reference(Path(path)):
                QMessageBox.warning(self, "Error", f"Cannot load image:\n{path}")

    def _on_regions_changed(self, regions: list) -> None:
        preset = self._working_presets.get(self._current_preset_id)
        if preset:
            preset.regions = regions

        for i, region in enumerate(regions):
            if i >= len(self._region_spins):
                break
            spins = self._region_spins[i]
            for field_name in ("x", "y", "width", "height"):
                spins[field_name].blockSignals(True)
                spins[field_name].setValue(getattr(region, field_name))
                spins[field_name].blockSignals(False)

    def _on_spin_changed(self) -> None:
        preset = self._working_presets.get(self._current_preset_id)
        if not preset:
            return

        for i, region in enumerate(preset.regions):
            if i >= len(self._region_spins):
                break
            spins = self._region_spins[i]
            for field_name in ("x", "y", "width", "height"):
                setattr(region, field_name, spins[field_name].value())

        self._canvas.set_regions(preset.regions)

    def _on_reset_preset(self) -> None:
        from app.core.region_config import RegionConfigManager as RCM
        defaults = RCM()
        preset_id = self._current_preset_id
        default_preset = defaults.get_preset(preset_id)
        if default_preset:
            self._working_presets[preset_id] = copy.deepcopy(default_preset)
            self._load_preset_into_editor(preset_id)

    def _on_save(self) -> None:
        s = self._settings
        s.default_preset = self._default_preset_combo.currentData()
        s.set("conflict_mode", self._conflict_combo.currentData())
        s.set("retry_limit", self._retry_spin.value())
        s.set("require_manual_review", self._review_check.isChecked())
        s.set("thumbnail_size", self._thumb_spin.value())
        s.set("preview_zoom_fit_on_select", self._fit_check.isChecked())
        s.set("log_verbosity", self._log_combo.currentText())

        for pid, preset in self._working_presets.items():
            ok, msg = self._region_mgr.update_preset(preset)
            if not ok:
                QMessageBox.warning(
                    self, "Validation Error",
                    f"Preset {pid} validation failed:\n{msg}"
                )
                return

        s.set_region_presets(self._region_mgr.to_dict())
        s.save()
        self.settings_saved.emit()
        self.accept()

    def _on_reset(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all settings to factory defaults?\n\n"
            "This does NOT delete images, logs, or output files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._settings.reset_to_defaults()
            self._region_mgr.reset_to_defaults()
            self._working_presets = {
                pid: copy.deepcopy(self._region_mgr.get_preset(pid))
                for pid in ("A", "B")
            }
            self._populate_values()
