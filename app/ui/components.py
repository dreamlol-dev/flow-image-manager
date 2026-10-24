"""
components.py — Reusable UI widgets and styles for Flow Image Manager.

Provides:
  - StatusBadge      : pill for image lifecycle state
  - StatCard         : metric card with accent color per metric
  - FolderSelector   : folder-path row with Browse / Open / action
  - ProgressSection  : animated progress bar + counters
  - SectionHeader    : uppercase divider label
  - APP_STYLESHEET   : global dark theme applied to QApplication
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.models.image_record import ImageStatus
from app.ui.icons import get_icon, get_pixmap


# ─────────────────────────────────────────────────────────────────────────────
# Design tokens
# ─────────────────────────────────────────────────────────────────────────────

PALETTE = {
    # Backgrounds
    "bg":              "#11121a",   # deep obsidian background
    "surface":         "#181926",   # card / panel background
    "surface_raised":  "#202234",   # elevated input/button background
    "surface_hover":   "#2a2d44",   # hover state over raised surface
    "surface_active":  "#343754",   # pressed state

    # Borders
    "border":          "#292b40",
    "border_light":    "#3a3d5c",
    "border_focus":    "#6c5ce7",

    # Text
    "text_primary":    "#f2f3fc",
    "text_secondary":  "#9fa3bf",
    "text_muted":      "#5e6280",

    # Accent
    "accent":          "#6c5ce7",
    "accent_light":    "#a29bfe",
    "accent_dim":      "#2d285c",

    # Semantic colours
    "success":         "#00b894",
    "warning":         "#fdcb6e",
    "error":           "#ff7675",
    "info":            "#74b9ff",
    "pending":         "#8a8ea8",
}

# Explicit RGBA tuples for badges and pills: (fg_hex, bg_rgba, border_rgba)
STATUS_BADGE_STYLE: dict[str, tuple[str, str, str]] = {
    ImageStatus.PENDING.value:      ("#8a8ea8", "rgba(138, 142, 168, 0.12)", "rgba(138, 142, 168, 0.30)"),
    ImageStatus.READY.value:        ("#74b9ff", "rgba(116, 185, 255, 0.14)", "rgba(116, 185, 255, 0.35)"),
    ImageStatus.PROCESSING.value:   ("#a29bfe", "rgba(162, 155, 254, 0.18)", "rgba(162, 155, 254, 0.45)"),
    ImageStatus.COMPLETED.value:    ("#00b894", "rgba(0, 184, 148, 0.14)",   "rgba(0, 184, 148, 0.35)"),
    ImageStatus.FAILED.value:       ("#ff7675", "rgba(255, 118, 117, 0.14)", "rgba(255, 118, 117, 0.35)"),
    ImageStatus.NEEDS_REVIEW.value: ("#fdcb6e", "rgba(253, 203, 110, 0.14)", "rgba(253, 203, 110, 0.35)"),
    ImageStatus.SKIPPED.value:      ("#8a8ea8", "rgba(138, 142, 168, 0.12)", "rgba(138, 142, 168, 0.30)"),
}

STATUS_LABELS: dict[str, str] = {
    ImageStatus.PENDING.value:      "Pending",
    ImageStatus.READY.value:        "Ready",
    ImageStatus.PROCESSING.value:   "Processing…",
    ImageStatus.COMPLETED.value:    "Completed",
    ImageStatus.FAILED.value:       "Failed",
    ImageStatus.NEEDS_REVIEW.value: "Needs Review",
    ImageStatus.SKIPPED.value:      "Skipped",
}

_STAT_ACCENTS = {
    "total":     PALETTE["accent_light"],
    "completed": PALETTE["success"],
    "failed":    PALETTE["error"],
    "remaining": PALETTE["info"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Global stylesheet
# ─────────────────────────────────────────────────────────────────────────────

APP_STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────────────────────────── */
* {{
    outline: none;
}}
QWidget {{
    background-color: {PALETTE['bg']};
    color: {PALETTE['text_primary']};
    font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
    font-size: 13px;
    selection-background-color: {PALETTE['accent_dim']};
    selection-color: {PALETTE['text_primary']};
}}

/* ── Surfaces ──────────────────────────────────────────────────────────── */
QFrame[class="surface"] {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 9px;
}}
QFrame[class="surface_raised"] {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border']};
    border-radius: 7px;
}}

/* ── Standard Buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background-color: {PALETTE['surface_raised']};
    color: {PALETTE['text_primary']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 6px;
    padding: 5px 12px;
    min-height: 20px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {PALETTE['surface_hover']};
    border-color: #4a4e75;
    color: #ffffff;
}}
QPushButton:pressed {{
    background-color: {PALETTE['surface_active']};
    border-color: {PALETTE['accent']};
}}
QPushButton:disabled {{
    background-color: #171824;
    color: {PALETTE['text_muted']};
    border-color: #222334;
}}

/* ── Primary Action Button ─────────────────────────────────────────────── */
QPushButton[primary="true"] {{
    background-color: {PALETTE['accent']};
    border: 1px solid {PALETTE['accent_light']};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background-color: #7b6cf0;
    border-color: #b5afff;
    color: #ffffff;
}}
QPushButton[primary="true"]:pressed {{
    background-color: {PALETTE['accent_dim']};
    border-color: {PALETTE['accent']};
}}
QPushButton[primary="true"]:disabled {{
    background-color: #1c1d2d;
    color: {PALETTE['text_muted']};
    border-color: #25263a;
}}

/* ── Danger Button (Stop / Reject) ─────────────────────────────────────── */
QPushButton[danger="true"] {{
    background-color: rgba(255, 118, 117, 0.12);
    border: 1px solid rgba(255, 118, 117, 0.40);
    color: {PALETTE['error']};
    font-weight: 600;
}}
QPushButton[danger="true"]:hover {{
    background-color: {PALETTE['error']};
    border-color: {PALETTE['error']};
    color: #ffffff;
}}
QPushButton[danger="true"]:pressed {{
    background-color: rgba(255, 118, 117, 0.30);
    color: {PALETTE['error']};
}}
QPushButton[danger="true"]:disabled {{
    background-color: #171824;
    color: {PALETTE['text_muted']};
    border-color: #222334;
}}

/* ── Flat Toolbar Button ───────────────────────────────────────────────── */
QPushButton[flat="true"] {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border']};
    color: {PALETTE['text_secondary']};
    border-radius: 5px;
    padding: 3px;
}}
QPushButton[flat="true"]:hover {{
    background-color: {PALETTE['surface_hover']};
    border-color: {PALETTE['border_light']};
    color: {PALETTE['text_primary']};
}}
QPushButton[flat="true"]:checked {{
    background-color: {PALETTE['accent_dim']};
    border-color: {PALETTE['accent']};
    color: {PALETTE['accent_light']};
}}

/* ── Inputs ────────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border']};
    border-radius: 6px;
    padding: 5px 9px;
    color: {PALETTE['text_primary']};
    min-height: 20px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {PALETTE['accent']};
    background-color: {PALETTE['surface_hover']};
}}

/* ── ComboBox ──────────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 6px;
    padding: 4px 10px;
    color: {PALETTE['text_primary']};
    min-height: 22px;
    padding-right: 28px;
}}
QComboBox:hover {{
    border-color: #4a4e75;
    background-color: {PALETTE['surface_hover']};
}}
QComboBox:focus {{
    border-color: {PALETTE['accent']};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {PALETTE['border']};
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background: transparent;
}}
QComboBox::down-arrow {{
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['text_secondary']};
    margin-right: 2px;
}}
QComboBox QAbstractItemView {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 6px;
    selection-background-color: {PALETTE['accent_dim']};
    selection-color: {PALETTE['accent_light']};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: 4px;
    min-height: 22px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {PALETTE['surface_hover']};
    color: {PALETTE['text_primary']};
}}

/* ── SpinBoxes ─────────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 6px;
    padding: 4px 8px;
    color: {PALETTE['text_primary']};
    min-height: 20px;
}}
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: #4a4e75;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {PALETTE['accent']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 18px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 4px solid {PALETTE['text_secondary']};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid {PALETTE['text_secondary']};
}}

/* ── CheckBox ──────────────────────────────────────────────────────────── */
QCheckBox {{
    spacing: 9px;
    color: {PALETTE['text_primary']};
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1.5px solid {PALETTE['border_light']};
    border-radius: 4px;
    background: {PALETTE['surface_raised']};
}}
QCheckBox::indicator:hover {{
    border-color: {PALETTE['accent']};
}}
QCheckBox::indicator:checked {{
    background-color: {PALETTE['accent']};
    border-color: {PALETTE['accent_light']};
}}

/* ── Progress bar ──────────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border']};
    border-radius: 6px;
    text-align: center;
    color: {PALETTE['text_primary']};
    min-height: 20px;
    font-size: 11px;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {PALETTE['accent']},
        stop:1 {PALETTE['accent_light']}
    );
    border-radius: 5px;
}}

/* ── List widget ───────────────────────────────────────────────────────── */
QListWidget {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    outline: none;
    padding: 3px;
}}
QListWidget::item {{
    border-radius: 6px;
    margin: 2px 2px;
    padding: 0px;
}}
QListWidget::item:hover {{
    background-color: {PALETTE['surface_raised']};
}}
QListWidget::item:selected {{
    background-color: {PALETTE['accent_dim']};
    border: 1px solid {PALETTE['accent']};
}}

/* ── Scroll bars ───────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 1px;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE['border_light']};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {PALETTE['accent']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 1px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {PALETTE['border_light']};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {PALETTE['accent']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Splitter ──────────────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {PALETTE['border']};
}}
QSplitter::handle:horizontal {{
    width: 2px;
    margin: 6px 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
    margin: 2px 6px;
}}

/* ── Tab widget ────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {PALETTE['text_secondary']};
    padding: 8px 22px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    min-width: 80px;
}}
QTabBar::tab:hover {{
    color: {PALETTE['text_primary']};
    background-color: {PALETTE['surface_raised']};
}}
QTabBar::tab:selected {{
    background-color: {PALETTE['surface']};
    color: {PALETTE['accent_light']};
    border-color: {PALETTE['border']};
    border-bottom: 2px solid {PALETTE['accent']};
    font-weight: 600;
}}

/* ── Group box ─────────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 12px;
    color: {PALETTE['text_secondary']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -7px;
    padding: 0 6px;
    background-color: {PALETTE['bg']};
    color: {PALETTE['text_primary']};
    font-weight: 600;
}}

/* ── Dialog ────────────────────────────────────────────────────────────── */
QDialog {{
    background-color: {PALETTE['bg']};
}}
QDialogButtonBox QPushButton {{
    min-width: 88px;
    padding: 6px 16px;
}}

/* ── Status bar ────────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {PALETTE['surface']};
    border-top: 1px solid {PALETTE['border']};
    color: {PALETTE['text_secondary']};
    font-size: 11px;
    padding: 3px 10px;
}}
QStatusBar::item {{
    border: none;
}}

/* ── Tool tips ─────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border_light']};
    border-radius: 5px;
    color: {PALETTE['text_primary']};
    padding: 5px 9px;
    font-size: 11px;
}}

/* ── Heading labels ────────────────────────────────────────────────────── */
QLabel[heading="true"] {{
    font-size: 18px;
    font-weight: 700;
    color: {PALETTE['text_primary']};
    letter-spacing: -0.3px;
}}
QLabel[subheading="true"] {{
    font-size: 11px;
    color: {PALETTE['text_secondary']};
    font-weight: 400;
}}

/* ── Message box ───────────────────────────────────────────────────────── */
QMessageBox {{
    background-color: {PALETTE['bg']};
}}
QMessageBox QLabel {{
    color: {PALETTE['text_primary']};
    font-size: 13px;
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# StatusBadge
# ─────────────────────────────────────────────────────────────────────────────

class StatusBadge(QLabel):
    """Pill badge showing image state with proper contrast."""

    def __init__(self, status: str = "pending", parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        style = STATUS_BADGE_STYLE.get(
            status, ("#8a8ea8", "rgba(138, 142, 168, 0.12)", "rgba(138, 142, 168, 0.30)")
        )
        fg, bg, border = style
        text = STATUS_LABELS.get(status, status.replace("_", " ").title())
        self.setText(text)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 1px 9px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }}
        """)


# ─────────────────────────────────────────────────────────────────────────────
# StatCard
# ─────────────────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    """Metric card showing large value and label with accent color stripe."""

    def __init__(
        self, label: str, value: str = "0",
        kind: str = "total", parent=None
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        accent = _STAT_ACCENTS.get(kind, PALETTE["accent_light"])

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(64)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['surface']};
                border: 1px solid {PALETTE['border']};
                border-radius: 9px;
                border-left: 3px solid {accent};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)

        self._value_lbl = QLabel(value)
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._value_lbl.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {accent}; "
            f"background: transparent; border: none; padding: 0px;"
        )

        self._label_lbl = QLabel(label)
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label_lbl.setStyleSheet(
            f"font-size: 11px; color: {PALETTE['text_secondary']}; "
            f"font-weight: 500; letter-spacing: 0.2px; "
            f"background: transparent; border: none; padding: 0px;"
        )

        lay.addWidget(self._value_lbl)
        lay.addWidget(self._label_lbl)

    def set_value(self, value: str | int) -> None:
        self._value_lbl.setText(str(value))


# ─────────────────────────────────────────────────────────────────────────────
# SectionHeader
# ─────────────────────────────────────────────────────────────────────────────

class SectionHeader(QLabel):
    """Uppercase section divider label."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text.upper(), parent)
        self.setStyleSheet(f"""
            QLabel {{
                color: {PALETTE['text_muted']};
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.2px;
                padding-bottom: 4px;
                border-bottom: 1px solid {PALETTE['border']};
                background: transparent;
            }}
        """)


# ─────────────────────────────────────────────────────────────────────────────
# FolderSelector
# ─────────────────────────────────────────────────────────────────────────────

class FolderSelector(QFrame):
    """
    Folder-picker panel:
      - Top row: Folder title + optional action button (e.g. Scan Images)
      - Bottom row: Path text field + Browse button + Open button
    """

    folder_changed = Signal(str)
    action_clicked = Signal()

    def __init__(
        self,
        label: str,
        placeholder: str = "No folder selected",
        action_label: str | None = None,
        action_icon: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "surface")
        self._path = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(7)

        # ── Top header row: Dot + Label + (optional Action Button) ───────────
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(12)
        self._dot.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 8px; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(label)
        title.setStyleSheet(
            f"font-weight: 600; font-size: 12px; color: {PALETTE['text_primary']}; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)

        title_row.addStretch()

        if action_label:
            self._action_btn = QPushButton(action_label)
            if action_icon:
                self._action_btn.setIcon(get_icon(action_icon, color="#ffffff", size=14))
            self._action_btn.setEnabled(False)
            self._action_btn.setProperty("primary", "true")
            self._action_btn.setFixedHeight(28)
            self._action_btn.setMinimumWidth(110)
            self._action_btn.clicked.connect(self.action_clicked)
            title_row.addWidget(self._action_btn)
        else:
            self._action_btn = None
            # Spacer label to keep height identical between Input and Output cards
            spacer = QLabel()
            spacer.setFixedHeight(28)
            spacer.setStyleSheet("background: transparent; border: none;")
            title_row.addWidget(spacer)

        outer.addLayout(title_row)

        # ── Bottom path row: [Path Box] [Browse] [Open] ──────────────────────
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.setContentsMargins(0, 0, 0, 0)

        path_box = QFrame()
        path_box.setStyleSheet(f"""
            QFrame {{
                background-color: {PALETTE['surface_raised']};
                border: 1px solid {PALETTE['border']};
                border-radius: 6px;
            }}
        """)
        path_box_lay = QHBoxLayout(path_box)
        path_box_lay.setContentsMargins(10, 4, 10, 4)

        self._path_lbl = QLabel(placeholder)
        self._path_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        self._path_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._path_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        path_box_lay.addWidget(self._path_lbl)
        path_row.addWidget(path_box, stretch=1)

        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setFixedSize(78, 30)
        self._browse_btn.setToolTip(f"Choose the {label.lower()}")
        path_row.addWidget(self._browse_btn)

        self._open_btn = QPushButton()
        self._open_btn.setIcon(get_icon("open", color=PALETTE["text_secondary"], size=14))
        self._open_btn.setFixedSize(30, 30)
        self._open_btn.setEnabled(False)
        self._open_btn.setToolTip("Open folder in Explorer")
        path_row.addWidget(self._open_btn)

        outer.addLayout(path_row)

        self._browse_btn.clicked.connect(self._on_browse)
        self._open_btn.clicked.connect(self._on_open)

    # ── Public ──────────────────────────────────────────────────────────────

    def set_path(self, path: str) -> None:
        self._path = path
        if path:
            display = path if len(path) <= 60 else "…" + path[-57:]
            self._path_lbl.setText(display)
            self._path_lbl.setToolTip(path)
            self._path_lbl.setStyleSheet(
                f"color: {PALETTE['text_primary']}; font-size: 11px; "
                f"background: transparent; border: none;"
            )
            self._dot.setStyleSheet(
                f"color: {PALETTE['success']}; font-size: 8px; "
                f"background: transparent; border: none;"
            )
            self._open_btn.setEnabled(True)
            if self._action_btn:
                self._action_btn.setEnabled(True)
        else:
            self._path_lbl.setText("No folder selected")
            self._path_lbl.setToolTip("")
            self._path_lbl.setStyleSheet(
                f"color: {PALETTE['text_muted']}; font-size: 11px; "
                f"background: transparent; border: none;"
            )
            self._dot.setStyleSheet(
                f"color: {PALETTE['text_muted']}; font-size: 8px; "
                f"background: transparent; border: none;"
            )
            self._open_btn.setEnabled(False)
            if self._action_btn:
                self._action_btn.setEnabled(False)

    def get_path(self) -> str:
        return self._path

    def set_action_enabled(self, enabled: bool) -> None:
        if self._action_btn:
            self._action_btn.setEnabled(enabled)

    # ── Private ─────────────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Folder",
            self._path or str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if path:
            self.set_path(path)
            self.folder_changed.emit(path)

    def _on_open(self) -> None:
        if self._path and Path(self._path).exists():
            os.startfile(self._path)


# ─────────────────────────────────────────────────────────────────────────────
# ProgressSection
# ─────────────────────────────────────────────────────────────────────────────

class ProgressSection(QFrame):
    """Progress bar + live metric pills with high contrast."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "surface")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 9)
        root.setSpacing(6)

        # Top row: Current task status label (left) + Elapsed / ETA (right)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)

        self._file_lbl = QLabel("Ready to process")
        self._file_lbl.setStyleSheet(
            f"font-size: 11px; color: {PALETTE['text_secondary']}; font-weight: 500; "
            f"background: transparent; border: none;"
        )
        top.addWidget(self._file_lbl, stretch=1)

        self._timing_lbl = QLabel("—")
        self._timing_lbl.setStyleSheet(
            f"font-size: 11px; color: {PALETTE['text_muted']}; "
            f"background: transparent; border: none;"
        )
        self._timing_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self._timing_lbl)
        root.addLayout(top)

        # Center: Progress bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFormat("Ready")
        self._bar.setFixedHeight(18)
        root.addWidget(self._bar)

        # Bottom row: Metric counter pills
        pills = QHBoxLayout()
        pills.setContentsMargins(0, 0, 0, 0)
        pills.setSpacing(8)

        self._done_pill = self._make_pill(
            "Completed", "0", PALETTE["success"], "rgba(0, 184, 148, 0.12)", "rgba(0, 184, 148, 0.35)"
        )
        self._fail_pill = self._make_pill(
            "Failed", "0", PALETTE["error"], "rgba(255, 118, 117, 0.12)", "rgba(255, 118, 117, 0.35)"
        )
        self._rem_pill = self._make_pill(
            "Remaining", "0", PALETTE["info"], "rgba(116, 185, 255, 0.12)", "rgba(116, 185, 255, 0.35)"
        )

        pills.addWidget(self._done_pill)
        pills.addWidget(self._fail_pill)
        pills.addWidget(self._rem_pill)
        pills.addStretch()

        root.addLayout(pills)

    # ── Pill helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_pill(label: str, value: str, text_color: str, bg_color: str, border_color: str) -> QFrame:
        pill = QFrame()
        pill.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 5px;
            }}
        """)
        row = QHBoxLayout(pill)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(6)

        v = QLabel(value)
        v.setObjectName("pill_value")
        v.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {text_color}; "
            f"background: transparent; border: none;"
        )

        l = QLabel(label)
        l.setStyleSheet(
            f"font-size: 10px; color: {PALETTE['text_secondary']}; "
            f"background: transparent; border: none; font-weight: 500;"
        )

        row.addWidget(v, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(l, alignment=Qt.AlignmentFlag.AlignVCenter)
        return pill

    @staticmethod
    def _set_pill_value(pill: QFrame, value: str) -> None:
        lbl = pill.findChild(QLabel, "pill_value")
        if lbl:
            lbl.setText(value)

    # ── Public API ───────────────────────────────────────────────────────────

    def update_progress(
        self,
        completed: int,
        failed: int,
        remaining: int,
        total: int,
        current_file: str,
        elapsed_s: float,
    ) -> None:
        if total > 0:
            pct = int((completed + failed) / total * 100)
            self._bar.setValue(pct)
            self._bar.setFormat(f"{pct}%  ({completed + failed}/{total})")
        else:
            self._bar.setValue(0)
            self._bar.setFormat("Ready")

        self._file_lbl.setText(f"Processing: {current_file}" if current_file else "—")
        self._set_pill_value(self._done_pill, str(completed))
        self._set_pill_value(self._fail_pill, str(failed))
        self._set_pill_value(self._rem_pill,  str(remaining))

        # Elapsed
        m, s = divmod(int(elapsed_s), 60)
        h, m = divmod(m, 60)
        if h:
            elapsed_str = f"{h}h {m}m"
        elif m:
            elapsed_str = f"{m}m {s}s"
        else:
            elapsed_str = f"{s}s"

        # ETA
        processed = completed + failed
        if processed > 0 and remaining > 0 and elapsed_s > 0:
            eta_s = int((elapsed_s / processed) * remaining)
            em, es = divmod(eta_s, 60)
            eh, em = divmod(em, 60)
            if eh:
                eta_str = f"ETA ~{eh}h {em}m"
            elif em:
                eta_str = f"ETA ~{em}m"
            else:
                eta_str = f"ETA ~{es}s"
            self._timing_lbl.setText(f"Elapsed: {elapsed_str}  ·  {eta_str}")
        else:
            self._timing_lbl.setText(f"Elapsed: {elapsed_str}")

    def reset(self) -> None:
        self._bar.setValue(0)
        self._bar.setFormat("Ready")
        self._file_lbl.setText("Ready to process")
        self._set_pill_value(self._done_pill, "0")
        self._set_pill_value(self._fail_pill, "0")
        self._set_pill_value(self._rem_pill,  "0")
        self._timing_lbl.setText("—")
