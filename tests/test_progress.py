"""
test_progress.py — Tests for ProgressSection and progress update behavior.
"""

import pytest
from PySide6.QtWidgets import QLabel
from app.ui.components import ProgressSection


def test_progress_section_update_and_finish(qapp):
    ps = ProgressSection()
    
    # 1. Initial state
    assert ps._bar.value() == 0
    assert ps._bar.format() == "Ready"
    
    # 2. Mid-batch update: 11 of 12
    ps.update_progress(
        completed=11,
        failed=0,
        remaining=1,
        total=12,
        current_file="scene_11.jpg",
        elapsed_s=4.5,
    )
    assert ps._bar.value() == 91
    assert "11/12" in ps._bar.format()
    
    # 3. Final completion state: 12 of 12
    ps.set_finished(
        completed=12,
        failed=0,
        total=12,
        duration_s=5.0,
        stopped=False,
    )
    assert ps._bar.value() == 100
    assert "Complete" in ps._bar.format()
    assert "12" in ps._file_lbl.text()
    
    done_lbl = ps._done_pill.findChild(QLabel, "pill_value")
    rem_lbl = ps._rem_pill.findChild(QLabel, "pill_value")
    assert done_lbl.text() == "12"
    assert rem_lbl.text() == "0"


def test_progress_section_stopped_state(qapp):
    ps = ProgressSection()
    ps.set_finished(
        completed=5,
        failed=1,
        total=12,
        duration_s=3.0,
        stopped=True,
    )
    assert ps._bar.value() == 50
    assert "Stopped" in ps._bar.format()
    assert "stopped" in ps._file_lbl.text().lower()

