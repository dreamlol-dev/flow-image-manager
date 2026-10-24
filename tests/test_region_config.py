"""
test_region_config.py — Tests for region configuration and presets.
"""

import pytest

from app.core.region_config import (
    NormalizedRegion,
    LayoutPreset,
    RegionConfigManager,
)


class TestNormalizedRegion:

    def test_valid_region(self):
        r = NormalizedRegion(x=0.5, y=0.5, width=0.1, height=0.1)
        ok, msg = r.validate()
        assert ok
        assert msg == ""

    def test_x_out_of_bounds(self):
        r = NormalizedRegion(x=1.5, y=0.0, width=0.1, height=0.1)
        ok, msg = r.validate()
        assert not ok
        assert "x" in msg

    def test_y_out_of_bounds(self):
        r = NormalizedRegion(x=0.0, y=-0.1, width=0.1, height=0.1)
        ok, msg = r.validate()
        assert not ok

    def test_width_overflow(self):
        r = NormalizedRegion(x=0.9, y=0.0, width=0.2, height=0.1)
        ok, msg = r.validate()
        assert not ok
        assert "width" in msg or "exceed" in msg

    def test_height_overflow(self):
        r = NormalizedRegion(x=0.0, y=0.9, width=0.1, height=0.2)
        ok, msg = r.validate()
        assert not ok

    def test_zero_width_invalid(self):
        r = NormalizedRegion(x=0.0, y=0.0, width=0.0, height=0.1)
        ok, msg = r.validate()
        assert not ok

    def test_to_pixel_rect(self):
        r = NormalizedRegion(x=0.5, y=0.5, width=0.1, height=0.1)
        left, top, right, bottom = r.to_pixel_rect(1000, 1000)
        assert left == 500
        assert top == 500
        assert right == 600
        assert bottom == 600

    def test_to_pixel_rect_different_resolution(self):
        """Scaling must work correctly for any image resolution."""
        r = NormalizedRegion(x=0.9, y=0.9, width=0.08, height=0.06)
        # 1920x1080
        left, top, right, bottom = r.to_pixel_rect(1920, 1080)
        assert left == int(0.9 * 1920)
        assert top == int(0.9 * 1080)
        # 3840x2160
        left2, top2, right2, bottom2 = r.to_pixel_rect(3840, 2160)
        assert left2 == int(0.9 * 3840)
        assert top2 == int(0.9 * 2160)

    def test_serialization_roundtrip(self):
        r = NormalizedRegion(x=0.92, y=0.93, width=0.07, height=0.06, label="mark")
        d = r.to_dict()
        r2 = NormalizedRegion.from_dict(d)
        assert r2.x == r.x
        assert r2.y == r.y
        assert r2.width == r.width
        assert r2.height == r.height
        assert r2.label == r.label


class TestLayoutPreset:

    def test_preset_a_valid(self):
        mgr = RegionConfigManager()
        preset = mgr.get_preset("A")
        ok, msg = preset.validate()
        assert ok, msg

    def test_preset_b_valid(self):
        mgr = RegionConfigManager()
        preset = mgr.get_preset("B")
        ok, msg = preset.validate()
        assert ok, msg

    def test_preset_with_no_regions_invalid(self):
        preset = LayoutPreset(preset_id="X", name="Empty", regions=[])
        ok, msg = preset.validate()
        assert not ok
        assert "no regions" in msg.lower()


class TestRegionConfigManager:

    def test_default_presets_loaded(self):
        mgr = RegionConfigManager()
        assert mgr.get_preset("A") is not None
        assert mgr.get_preset("B") is not None

    def test_preset_a_has_one_region(self):
        mgr = RegionConfigManager()
        preset = mgr.get_preset("A")
        assert len(preset.regions) == 1

    def test_preset_b_has_two_regions(self):
        mgr = RegionConfigManager()
        preset = mgr.get_preset("B")
        assert len(preset.regions) == 2

    def test_update_preset(self):
        mgr = RegionConfigManager()
        preset = mgr.get_preset("A")
        preset.regions[0].x = 0.85
        ok, msg = mgr.update_preset(preset)
        assert ok
        assert mgr.get_preset("A").regions[0].x == 0.85

    def test_update_invalid_preset_rejected(self):
        mgr = RegionConfigManager()
        preset = mgr.get_preset("A")
        preset.regions[0].x = 1.5   # invalid
        ok, msg = mgr.update_preset(preset)
        assert not ok

    def test_reset_to_defaults(self):
        mgr = RegionConfigManager()
        mgr.get_preset("A").regions[0].x = 0.0
        mgr.reset_to_defaults()
        # Default x for preset A is 0.92
        assert mgr.get_preset("A").regions[0].x == pytest.approx(0.92, abs=0.01)

    def test_serialization_roundtrip(self):
        mgr = RegionConfigManager()
        data = mgr.to_dict()
        mgr2 = RegionConfigManager()
        mgr2.from_dict(data)
        for pid in ("A", "B"):
            p1 = mgr.get_preset(pid)
            p2 = mgr2.get_preset(pid)
            assert len(p1.regions) == len(p2.regions)
            for r1, r2 in zip(p1.regions, p2.regions):
                assert r1.x == pytest.approx(r2.x)
                assert r1.y == pytest.approx(r2.y)

    def test_missing_preset_returns_none(self):
        mgr = RegionConfigManager()
        assert mgr.get_preset("Z") is None

