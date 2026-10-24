"""
icons.py — High-DPI scalable vector icon generator for Flow Image Manager.

Provides crisp SVG-based icons for buttons, tabs, and status indicators
without relying on missing font glyphs or OS emoji.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# SVG path definitions (24x24 viewBox)
SVG_PATHS: dict[str, str] = {
    "play": '<polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/>',
    "refresh": '<path d="M21 2v6h-6M3 12a9 9 0 0 1 15.5-6.3L21 8M3 22v-6h6M21 12a9 9 0 0 1-15.5 6.3L3 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    "settings": '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" fill="none" stroke="currentColor" stroke-width="2"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "open": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2" ry="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="8.5" cy="8.5" r="1.5" fill="currentColor"/><polyline points="21 15 16 10 5 21" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "zoom-in": '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><line x1="21" y1="21" x2="16" y2="16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="11" y1="8" x2="11" y2="14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="8" y1="11" x2="14" y2="11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "zoom-out": '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><line x1="21" y1="21" x2="16" y2="16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="8" y1="11" x2="14" y2="11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "fit": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "trash": '<polyline points="3 6 5 6 21 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "check": '<polyline points="20 6 9 17 4 12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><polyline points="2 17 12 22 22 17" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><polyline points="2 12 12 17 22 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
}


def get_icon(name: str, color: str = "#f0f1fc", size: int = 16) -> QIcon:
    """
    Generate a crisp QIcon from a registered vector path.

    Supports disabled state rendering automatically.
    """
    path_data = SVG_PATHS.get(name)
    if not path_data:
        return QIcon()

    icon = QIcon()

    # Normal state
    pix_normal = _render_svg_pixmap(path_data, color, size)
    icon.addPixmap(pix_normal, QIcon.Mode.Normal)

    # Disabled state (muted color)
    pix_disabled = _render_svg_pixmap(path_data, "#555870", size)
    icon.addPixmap(pix_disabled, QIcon.Mode.Disabled)

    return icon


def get_pixmap(name: str, color: str = "#616480", size: int = 48) -> QPixmap:
    """Render an SVG icon directly as a QPixmap (e.g. for empty state illustrations)."""
    path_data = SVG_PATHS.get(name, "")
    if not path_data:
        return QPixmap()
    return _render_svg_pixmap(path_data, color, size)


def _render_svg_pixmap(path_content: str, color: str, size: int) -> QPixmap:
    svg_template = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" style="color:{color};">
{path_content}
</svg>"""
    data = QByteArray(svg_template.encode("utf-8"))
    renderer = QSvgRenderer(data)
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return pix

