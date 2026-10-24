"""
image_preview.py — Zoomable, pannable image preview widget.

Features:
  - Fit-to-panel and actual-size modes.
  - Smooth zoom with mouse wheel.
  - Click-drag panning when zoomed.
  - Region overlay rectangles (normalized coordinates → screen coordinates).
  - No modification of the source image on display.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QRectF, QPointF, QSizeF, Signal, QPoint
)
from PySide6.QtGui import (
    QColor, QImage, QPainter, QPen, QPixmap, QTransform, QWheelEvent,
    QMouseEvent, QPaintEvent, QResizeEvent, QFont, QBrush
)
from PySide6.QtWidgets import QLabel, QWidget, QSizePolicy, QVBoxLayout

from app.core.region_config import NormalizedRegion, LayoutPreset
from app.ui.components import PALETTE


# ─────────────────────────────────────────────────────────────────────────────
# Overlay colors for preset regions
# ─────────────────────────────────────────────────────────────────────────────
_REGION_COLORS = [
    QColor(108, 92, 231),   # accent purple (#6c5ce7)
    QColor(0, 184, 148),    # emerald green (#00b894)
]


class ImagePreviewWidget(QWidget):
    """
    Widget that renders a single image with optional region overlays.

    The image is never written to disk.  Only the display transform changes.
    """

    zoom_changed = Signal(float)  # current zoom factor

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 220)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMouseTracking(True)

        self._pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._fit_mode: bool = True          # True = fit-to-panel
        self._pan_offset: QPointF = QPointF(0, 0)
        self._pan_start: Optional[QPoint] = None
        self._pan_origin: Optional[QPointF] = None
        self._regions: list[NormalizedRegion] = []
        self._show_regions: bool = True

        self._info_text: str = ""

    # ── Public API ──────────────────────────────────────────────────────────

    def load_image(self, path: Path | str) -> bool:
        """
        Load and display an image from *path*.
        The source file is opened read-only.
        """
        path = Path(path)
        if not path.exists():
            self._pixmap = None
            self._info_text = f"File not found:\n{path.name}"
            self.update()
            return False

        qimg = QImage(str(path))
        if qimg.isNull():
            self._pixmap = None
            self._info_text = f"Cannot display:\n{path.name}"
            self.update()
            return False

        self._pixmap = QPixmap.fromImage(qimg)
        self._info_text = ""
        self._reset_view()
        self.update()
        return True

    def load_pixmap(self, pixmap: QPixmap) -> None:
        """Display a pixmap directly."""
        self._pixmap = pixmap
        self._info_text = ""
        self._reset_view()
        self.update()

    def clear(self) -> None:
        """Clear the display."""
        self._pixmap = None
        self._info_text = ""
        self.update()

    def set_info(self, text: str) -> None:
        """Set the overlay information text."""
        self._info_text = text
        self.update()

    def set_regions(self, regions: list[NormalizedRegion]) -> None:
        """Set the list of regions to overlay on the image."""
        self._regions = list(regions)
        self.update()

    def set_show_regions(self, visible: bool) -> None:
        self._show_regions = visible
        self.update()

    def set_fit_mode(self, fit: bool) -> None:
        """Toggle between fit-to-panel and actual-size modes."""
        self._fit_mode = fit
        self._reset_view()
        self.update()

    def toggle_fit_actual(self) -> None:
        self.set_fit_mode(not self._fit_mode)

    @property
    def zoom(self) -> float:
        return self._zoom

    def zoom_in(self) -> None:
        self._apply_zoom(1.2)

    def zoom_out(self) -> None:
        self._apply_zoom(1 / 1.2)

    def zoom_reset(self) -> None:
        self._fit_mode = True
        self._reset_view()
        self.update()

    # ── Qt overrides ────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Background
        painter.fillRect(self.rect(), QColor(PALETTE["bg"]))

        if self._pixmap is None or self._pixmap.isNull():
            self._draw_empty(painter)
            return

        # Image transform
        transform = self._build_transform()
        painter.setTransform(transform)
        painter.drawPixmap(0, 0, self._pixmap)

        # Region overlays
        if self._show_regions and self._regions:
            self._draw_regions(painter)

        painter.resetTransform()

        if self._info_text:
            self._draw_info(painter)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._fit_mode:
            self._reset_view()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap is None:
            return
        delta = event.angleDelta().y()
        factor = 1.12 if delta > 0 else 1 / 1.12
        self._fit_mode = False
        self._apply_zoom(factor, event.position())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self._pan_start = event.pos()
            self._pan_origin = QPointF(self._pan_offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_offset = self._pan_origin + QPointF(delta)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pan_start = None
        self._pan_origin = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.toggle_fit_actual()

    # ── Private helpers ─────────────────────────────────────────────────────

    def _reset_view(self) -> None:
        self._pan_offset = QPointF(0, 0)
        if self._pixmap and not self._pixmap.isNull() and self._fit_mode:
            self._zoom = self._fit_zoom()
        self.zoom_changed.emit(self._zoom)

    def _fit_zoom(self) -> float:
        if not self._pixmap or self._pixmap.isNull():
            return 1.0
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = self.width() - 8
        wh = self.height() - 8
        if pw <= 0 or ph <= 0 or ww <= 0 or wh <= 0:
            return 1.0
        return min(ww / pw, wh / ph)

    def _apply_zoom(
        self, factor: float, center: Optional[QPointF] = None
    ) -> None:
        old_zoom = self._zoom
        new_zoom = max(0.05, min(20.0, self._zoom * factor))
        if center is None:
            center = QPointF(self.width() / 2, self.height() / 2)
        self._pan_offset = (
            center - (center - self._pan_offset) * (new_zoom / old_zoom)
        )
        self._zoom = new_zoom
        self.zoom_changed.emit(self._zoom)
        self.update()

    def _build_transform(self) -> QTransform:
        if self._pixmap is None:
            return QTransform()
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ww = self.width()
        wh = self.height()

        if self._fit_mode:
            zoom = self._fit_zoom()
            tx = (ww - pw * zoom) / 2
            ty = (wh - ph * zoom) / 2
        else:
            zoom = self._zoom
            tx = self._pan_offset.x() + (ww - pw * zoom) / 2
            ty = self._pan_offset.y() + (wh - ph * zoom) / 2

        t = QTransform()
        t.translate(tx, ty)
        t.scale(zoom, zoom)
        return t

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor(PALETTE["text_muted"]))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            self._info_text or "Select an image from the queue to preview",
        )

    def _draw_regions(self, painter: QPainter) -> None:
        if not self._pixmap:
            return
        pw = self._pixmap.width()
        ph = self._pixmap.height()

        for i, region in enumerate(self._regions):
            color = _REGION_COLORS[i % len(_REGION_COLORS)]

            # Semi-transparent fill
            fill = QColor(color)
            fill.setAlpha(45)
            painter.setBrush(QBrush(fill))

            # Cosmetic pen so line width stays crisp at all zoom levels
            pen = QPen(color, 2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)

            # Normalized → image-space pixels
            x = region.x * pw
            y = region.y * ph
            w = region.width * pw
            h = region.height * ph
            rect = QRectF(x, y, w, h)
            painter.drawRect(rect)

            # Contrast-preserving badge for label
            label = region.label or f"Region {i + 1}"
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            tw = painter.fontMetrics().horizontalAdvance(label) + 8
            th = 18

            pill_bg = QColor(PALETTE["surface_raised"])
            pill_bg.setAlpha(220)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(pill_bg))
            painter.drawRoundedRect(QRectF(x + 3, y + 3, tw, th), 3, 3)

            painter.setPen(QPen(color))
            painter.drawText(
                QRectF(x + 7, y + 3, tw - 4, th),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _draw_info(self, painter: QPainter) -> None:
        painter.setPen(QColor(PALETTE["text_secondary"]))
        painter.setFont(QFont("Segoe UI", 10))
        rect = self.rect()
        rect.setLeft(10)
        rect.setBottom(rect.bottom() - 8)
        rect.setTop(rect.bottom() - 60)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            self._info_text,
        )
