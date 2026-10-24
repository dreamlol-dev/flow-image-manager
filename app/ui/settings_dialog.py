"""
settings_dialog.py — Application settings and region-configuration dialog.

Two tabs:
  1. General Settings — folders, presets, processing options, logging
  2. Region Presets — interactive region editor with image overlay

The region editor lets the user:
  - Pick a preset (A or B).
  - Load a reference image.
  - Smoothly zoom (mouse wheel, buttons, or Zoom to Mark).
  - Pan freely across the image.
  - Drag rectangle handles to reposition / resize each region with high precision.
  - Keep watermark artwork 100% visible with external labels and toggleable fill.
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
    QPaintEvent, QWheelEvent
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
    Interactive canvas displaying a reference image with zoom, pan,
    and drag-resizable normalized region rectangles.

    Features:
      - Smooth cursor-centered mouse wheel zoom (0.5x to 16x).
      - Click-and-drag panning (Middle-drag, Right-drag, or Left-drag on background).
      - One-click zoom directly to watermark mark coordinates (4x).
      - Unobtrusive labels positioned outside the region boxes to prevent blocking artwork.
      - Toggleable labels and box fill for 100% transparent pixel visibility.
      - Corner handles for accurate resizing.
    """

    regions_changed = Signal(list)   # list[NormalizedRegion]
    zoom_changed    = Signal(float)  # current zoom factor
    region_selected = Signal(int)    # selected region index

    _HANDLE_SIZE = 8   # handle square dimension in pixels
    _MIN_DIM     = 0.005  # minimum normalized region dimension

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(440, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._pixmap: Optional[QPixmap] = None
        self._regions: list[NormalizedRegion] = []
        self._colors = [
            QColor(108, 92, 231),  # purple (#6c5ce7)
            QColor(0, 184, 148),   # emerald (#00b894)
            QColor(253, 203, 110), # gold (#fdcb6e)
        ]

        # Zoom & Pan state
        self._zoom: float = 1.0
        self._pan_offset: QPointF = QPointF(0, 0)
        self._is_panning: bool = False
        self._pan_start_pos: QPointF = QPointF()

        # Display options
        self._show_labels: bool = True
        self._show_fill: bool = True
        self._selected_region_idx: int = -1

        # Drag-resize state
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
        self.zoom_fit()
        return True

    def set_regions(self, regions: list[NormalizedRegion]) -> None:
        self._regions = [copy.deepcopy(r) for r in regions]
        self.update()

    def get_regions(self) -> list[NormalizedRegion]:
        return [copy.deepcopy(r) for r in self._regions]

    def set_show_labels(self, show: bool) -> None:
        self._show_labels = show
        self.update()

    def set_show_fill(self, show: bool) -> None:
        self._show_fill = show
        self.update()

    # ── Zoom & Pan API ──────────────────────────────────────────────────────

    @property
    def zoom(self) -> float:
        return self._zoom

    def zoom_in(self) -> None:
        self.zoom_at(1.3, QPointF(self.width() / 2, self.height() / 2))

    def zoom_out(self) -> None:
        self.zoom_at(1 / 1.3, QPointF(self.width() / 2, self.height() / 2))

    def zoom_fit(self) -> None:
        self._zoom = 1.0
        self._pan_offset = QPointF(0, 0)
        self.update()
        self.zoom_changed.emit(1.0)

    def zoom_to_mark(self, zoom_factor: float = 4.0) -> None:
        """Instantly centers and magnifies the region area (or bottom-right)."""
        if not self._pixmap or self._pixmap.isNull():
            return

        if self._regions:
            min_x = min(r.x for r in self._regions)
            max_x = max(r.x + r.width for r in self._regions)
            min_y = min(r.y for r in self._regions)
            max_y = max(r.y + r.height for r in self._regions)
            target_nx = (min_x + max_x) / 2
            target_ny = (min_y + max_y) / 2
        else:
            target_nx, target_ny = 0.9495, 0.9093

        self._zoom = zoom_factor
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = max(10, self.width() - 20)
        wh = max(10, self.height() - 20)
        base_scale = min(ww / pw, wh / ph)
        new_sw = pw * base_scale * zoom_factor
        new_sh = ph * base_scale * zoom_factor

        canvas_cx = self.width() / 2
        canvas_cy = self.height() / 2
        new_pan_x = (canvas_cx - target_nx * new_sw) - (self.width() - new_sw) / 2
        new_pan_y = (canvas_cy - target_ny * new_sh) - (self.height() - new_sh) / 2
        self._pan_offset = QPointF(new_pan_x, new_pan_y)
        self.update()
        self.zoom_changed.emit(self._zoom)

    def zoom_at(self, factor: float, center_pos: QPointF) -> None:
        """Zoom centered at a specific canvas position."""
        if not self._pixmap or self._pixmap.isNull():
            return
        old_rect = self._scaled_image_rect()
        old_zoom = self._zoom
        new_zoom = max(0.5, min(16.0, self._zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-4:
            return

        if old_rect.width() > 0 and old_rect.height() > 0:
            nx = (center_pos.x() - old_rect.left()) / old_rect.width()
            ny = (center_pos.y() - old_rect.top()) / old_rect.height()
        else:
            nx, ny = 0.5, 0.5

        self._zoom = new_zoom
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = max(10, self.width() - 20)
        wh = max(10, self.height() - 20)
        base_scale = min(ww / pw, wh / ph)
        new_sw = pw * base_scale * new_zoom
        new_sh = ph * base_scale * new_zoom

        new_pan_x = (center_pos.x() - nx * new_sw) - (self.width() - new_sw) / 2
        new_pan_y = (center_pos.y() - ny * new_sh) - (self.height() - new_sh) / 2
        self._pan_offset = QPointF(new_pan_x, new_pan_y)
        self.update()
        self.zoom_changed.emit(self._zoom)

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(PALETTE["bg"]))

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(PALETTE["text_muted"]))
            painter.setFont(QFont("Segoe UI Variable Text", 12))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Load a reference image to calibrate preset regions\n(Click 'Load Reference Image…' above)"
            )
            return

        img_rect = self._scaled_image_rect()
        painter.drawPixmap(img_rect.toRect(), self._pixmap)

        # Subtle outer border around image
        painter.setPen(QPen(QColor(PALETTE["border_light"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(img_rect)

        # Regions
        for i, region in enumerate(self._regions):
            color = self._colors[i % len(self._colors)]
            self._draw_region(painter, region, color, i, img_rect)

    def _draw_region(
        self, painter: QPainter, region: NormalizedRegion,
        color: QColor, idx: int, img_rect: QRectF
    ) -> None:
        rx = img_rect.left() + region.x * img_rect.width()
        ry = img_rect.top() + region.y * img_rect.height()
        rw = region.width * img_rect.width()
        rh = region.height * img_rect.height()
        rect = QRectF(rx, ry, rw, rh)

        # 1. Subtle translucent fill (if enabled)
        if self._show_fill:
            fill = QColor(color)
            fill.setAlpha(20)  # very subtle 8% tint so image pixels remain crystal clear
            painter.fillRect(rect, fill)

        # 2. High-contrast outline
        pen = QPen(color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # 3. Subtle alignment guide crosshairs in center (never obstructs text)
        if rw > 14 and rh > 14:
            cx = rx + rw / 2
            cy = ry + rh / 2
            guide_pen = QPen(QColor(color.red(), color.green(), color.blue(), 100), 1, Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            painter.drawLine(QPointF(rx + 3, cy), QPointF(rx + rw - 3, cy))
            painter.drawLine(QPointF(cx, ry + 3), QPointF(cx, ry + rh - 3))

        # 4. Corner resize handles
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

        # 5. Label badge: positioned OUTSIDE the box so it NEVER blocks the watermark!
        if self._show_labels:
            label_text = region.label or f"Region {idx + 1}"
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(label_text) + 12
            text_h = 18

            # Place above the box; if too close to top edge, place below
            badge_y = ry - text_h - 4
            if badge_y < img_rect.top() + 2:
                badge_y = ry + rh + 4

            badge_x = max(img_rect.left(), min(rx, img_rect.right() - text_w))
            pill_rect = QRectF(badge_x, badge_y, text_w, text_h)

            badge_bg = QColor(PALETTE["surface_raised"])
            badge_bg.setAlpha(235)
            painter.setPen(QPen(color, 1))
            painter.setBrush(QBrush(badge_bg))
            painter.drawRoundedRect(pill_rect, 4, 4)

            painter.setPen(QPen(QColor(PALETTE["text_primary"])))
            painter.drawText(
                pill_rect,
                Qt.AlignmentFlag.AlignCenter,
                label_text,
            )

    # ── Mouse & Wheel events ────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0 or not self._pixmap or self._pixmap.isNull():
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.zoom_at(factor, event.position())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = QPointF(event.position())
        # Right or middle click starts panning
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._is_panning = True
            self._pan_start_pos = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            hit_idx, hit_handle = self._hit_test(pos)
            if hit_idx >= 0:
                self._drag_region_idx = hit_idx
                self._drag_handle = hit_handle
                self._drag_start_pos = pos
                self._drag_start_region = copy.deepcopy(self._regions[hit_idx])
                self.region_selected.emit(hit_idx)
            else:
                # Left click on canvas background starts panning
                self._is_panning = True
                self._pan_start_pos = pos
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = QPointF(event.position())

        if self._is_panning:
            delta = pos - self._pan_start_pos
            self._pan_offset += delta
            self._pan_start_pos = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            return

        if self._drag_region_idx >= 0:
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
            return

        # Cursor shape when hovering
        hit_idx, hit_handle = self._hit_test(pos)
        if hit_handle in ("nw", "se"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif hit_handle in ("ne", "sw"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif hit_handle == "body":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if (self._pixmap and not self._pixmap.isNull()) else Qt.CursorShape.ArrowCursor
            )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._is_panning = False
        self._drag_region_idx = -1
        self._drag_handle = ""
        self._drag_start_region = None
        pos = QPointF(event.position())
        hit_idx, hit_handle = self._hit_test(pos)
        if hit_handle in ("nw", "se"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif hit_handle in ("ne", "sw"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif hit_handle == "body":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if (self._pixmap and not self._pixmap.isNull()) else Qt.CursorShape.ArrowCursor
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _scaled_image_rect(self) -> QRectF:
        if not self._pixmap or self._pixmap.isNull():
            return QRectF(self.rect())
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = max(10, self.width() - 20)
        wh = max(10, self.height() - 20)
        base_scale = min(ww / pw, wh / ph)
        total_scale = base_scale * self._zoom
        sw = pw * total_scale
        sh = ph * total_scale
        ox = (self.width() - sw) / 2 + self._pan_offset.x()
        oy = (self.height() - sh) / 2 + self._pan_offset.y()
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
        self.setMinimumSize(940, 640)
        self.resize(1020, 700)

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
        self._conflict_combo.addItem("Unique name (append _1, _2)", "unique")
        self._conflict_combo.addItem("Skip existing file", "skip")
        self._conflict_combo.setFixedWidth(240)
        proc_form.addRow("Filename Conflict:", self._conflict_combo)

        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 10)
        self._retry_spin.setValue(2)
        self._retry_spin.setFixedWidth(70)
        proc_form.addRow("Retry Limit:", self._retry_spin)

        self._review_check = QCheckBox("Require manual review before completing")
        proc_form.addRow("", self._review_check)

        layout.addWidget(proc_group)

        # ── UI & Display group ─────────────────────────────────────────────
        disp_group = QGroupBox("Display & Performance")
        disp_form = QFormLayout(disp_group)
        disp_form.setSpacing(10)
        disp_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._thumb_spin = QSpinBox()
        self._thumb_spin.setRange(64, 512)
        self._thumb_spin.setSingleStep(32)
        self._thumb_spin.setValue(128)
        self._thumb_spin.setSuffix(" px")
        self._thumb_spin.setFixedWidth(100)
        disp_form.addRow("Thumbnail Size:", self._thumb_spin)

        self._fit_check = QCheckBox("Automatically fit image to panel on selection")
        self._fit_check.setChecked(True)
        disp_form.addRow("", self._fit_check)

        layout.addWidget(disp_group)

        # ── Logging group ──────────────────────────────────────────────────
        log_group = QGroupBox("Logging")
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
        self._preset_combo.setFixedWidth(260)  # Generous width so no label truncation
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

        # Canvas with rounded border container & integrated controls toolbar
        canvas_container = QFrame()
        canvas_container.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['bg']};
                border: 1px solid {PALETTE['border']};
                border-radius: 8px;
            }}
        """)
        canvas_lay = QVBoxLayout(canvas_container)
        canvas_lay.setContentsMargins(6, 6, 6, 6)
        canvas_lay.setSpacing(6)

        # ── Canvas Interactive Toolbar ──────────────────────────────────────
        canvas_tb = QFrame()
        canvas_tb.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['surface_raised']};
                border: 1px solid {PALETTE['border_light']};
                border-radius: 6px;
            }}
        """)
        tb_lay = QHBoxLayout(canvas_tb)
        tb_lay.setContentsMargins(8, 4, 8, 4)
        tb_lay.setSpacing(6)

        self._canvas = RegionEditorCanvas()
        self._canvas.regions_changed.connect(self._on_regions_changed)

        zoom_in_btn = QPushButton()
        zoom_in_btn.setIcon(get_icon("zoom-in", color=PALETTE["text_primary"], size=14))
        zoom_in_btn.setToolTip("Zoom In (or scroll wheel up)")
        zoom_in_btn.setFixedSize(28, 28)
        zoom_in_btn.clicked.connect(self._canvas.zoom_in)
        tb_lay.addWidget(zoom_in_btn)

        zoom_out_btn = QPushButton()
        zoom_out_btn.setIcon(get_icon("zoom-out", color=PALETTE["text_primary"], size=14))
        zoom_out_btn.setToolTip("Zoom Out (or scroll wheel down)")
        zoom_out_btn.setFixedSize(28, 28)
        zoom_out_btn.clicked.connect(self._canvas.zoom_out)
        tb_lay.addWidget(zoom_out_btn)

        fit_btn = QPushButton("Fit")
        fit_btn.setIcon(get_icon("fit", color=PALETTE["text_primary"], size=13))
        fit_btn.setToolTip("Fit entire image to window")
        fit_btn.setFixedHeight(28)
        fit_btn.clicked.connect(self._canvas.zoom_fit)
        tb_lay.addWidget(fit_btn)

        tb_lay.addSpacing(4)

        # Dedicated 1-click zoom to mark area!
        zoom_mark_btn = QPushButton("🎯 Zoom to Mark (4x)")
        zoom_mark_btn.setProperty("primary", "true")
        zoom_mark_btn.setToolTip("Instantly magnify 400% directly into the bottom-right watermark area for pixel-perfect positioning")
        zoom_mark_btn.setFixedHeight(28)
        zoom_mark_btn.clicked.connect(lambda: self._canvas.zoom_to_mark(4.0))
        tb_lay.addWidget(zoom_mark_btn)

        tb_lay.addSpacing(6)

        # Labels toggle button (prevents blocking watermark artwork)
        self._labels_btn = QPushButton("Labels")
        self._labels_btn.setIcon(get_icon("tag", color=PALETTE["text_primary"], size=13))
        self._labels_btn.setCheckable(True)
        self._labels_btn.setChecked(True)
        self._labels_btn.setToolTip("Toggle text labels above region boxes on/off")
        self._labels_btn.setFixedHeight(28)
        self._labels_btn.toggled.connect(self._canvas.set_show_labels)
        tb_lay.addWidget(self._labels_btn)

        # Box fill toggle button
        self._fill_btn = QPushButton("Fill Tint")
        self._fill_btn.setIcon(get_icon("layers", color=PALETTE["text_primary"], size=13))
        self._fill_btn.setCheckable(True)
        self._fill_btn.setChecked(True)
        self._fill_btn.setToolTip("Toggle translucent box fill on/off to see raw image pixels")
        self._fill_btn.setFixedHeight(28)
        self._fill_btn.toggled.connect(self._canvas.set_show_fill)
        tb_lay.addWidget(self._fill_btn)

        tb_lay.addStretch()

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {PALETTE['accent_light']}; padding: 0 4px;")
        self._canvas.zoom_changed.connect(lambda z: self._zoom_lbl.setText(f"{int(z * 100)}%"))
        tb_lay.addWidget(self._zoom_lbl)

        canvas_lay.addWidget(canvas_tb)
        canvas_lay.addWidget(self._canvas, stretch=1)

        hint_lbl = QLabel("💡 Scroll wheel to zoom · Drag canvas (or Right-click) to pan · Drag corner handles to resize")
        hint_lbl.setStyleSheet(f"font-size: 11px; color: {PALETTE['text_muted']}; padding: 2px 4px; background: transparent;")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        canvas_lay.addWidget(hint_lbl)

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
        splitter.setSizes([640, 270])
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
            else:
                # Automatically focus 4x onto watermark area for convenience
                self._canvas.zoom_to_mark(3.5)

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
