"""End-to-end integration tests: settings → synthesis → assembly → report.

These tests exercise the full pipeline without a KiCad connection.
"""

import json
import math
import os
import tempfile

import numpy as np
import pytest

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import TaperAssembly
from rfcore.reports import TaperReport
from rfcore.discontinuities.step import WidthStepBlock
from rfcore.discontinuities.pad import PadBlock
from rfcore.discontinuities.via_signal import SignalViaSelfBlock
from rfcore.discontinuities.stub import StubBlock
from rfcore.discontinuities.return_path import ReturnPathBlock
from rfcore.materials_ro4350b import RO4350B
from addon.ui_main import (
    SynthesisRequest, synthesize_taper, synthesize_with_discontinuities,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    s = RFProjectSettings()
    s.analysis.n_points = 31  # fast tests
    s.analysis.f_stop_hz = 10e9
    return s


@pytest.fixture
def ms(settings):
    return MicrostripModel.from_settings(settings)


# ---------------------------------------------------------------------------
# Test: Full synthesis pipeline (headless, no disconts)
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """End-to-end: settings → synthesis → assembly → report."""

    def test_50_to_75_headless(self, settings):
        """Headless synthesis of 50→75Ω taper produces valid report."""
        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)
        result, report, profile = synthesize_taper(request, settings)

        # Result is valid
        assert result.freqs.shape[0] == 31
        assert result.s_params.shape == (31, 2, 2)

        # Report generates without error
        text = report.to_text()
        assert "KLOPFENSTEIN MICROSTRIP TAPER" in text
        assert "S-PARAMETER SUMMARY" in text
        assert "MODEL ASSUMPTIONS" in text
        assert "Hammerstad" in text

        json_str = report.to_json()
        d = json.loads(json_str)
        assert d["report_version"] == "1.0"
        assert d["profile"]["ZS_ohm"] == 50.0
        assert d["profile"]["ZL_ohm"] == 75.0
        assert len(d["s_params_data"]) == 31

    def test_default_settings(self):
        """Synthesis with all defaults produces a result."""
        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=100.0, Gamma_m=0.03)
        result, report, profile = synthesize_taper(request)

        assert result.s_params.shape[0] > 0
        assert profile.L > 0

    def test_fixed_length(self, settings):
        """Fixed-length synthesis uses the specified length."""
        request = SynthesisRequest(
            ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05,
            L_fixed_m=20e-3,
        )
        result, report, profile = synthesize_taper(request, settings)
        assert profile.L == 20e-3


# ---------------------------------------------------------------------------
# Test: Full pipeline WITH discontinuities
# ---------------------------------------------------------------------------

class TestPipelineWithDiscontinuities:
    """End-to-end with realistic via transition chain."""

    def test_50_to_75_with_via_chain(self, settings, ms):
        """Full chain with pad + via + stub + return path."""
        h = settings.stackup.substrate_height_m
        er = settings.stackup.dk_design
        sigma = settings.stackup.conductivity_s_per_m

        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)

        # Build right-side via transition chain
        profile = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.05,
            microstrip=ms, f_min=settings.analysis.f_start_hz,
            f_geom=settings.analysis.f_geom,
        )
        w_end = float(profile.w_profile[-1])

        right_blocks = [
            PadBlock(w_end, w_end, 0.7e-3, 0.7e-3, h, er, ms),
            SignalViaSelfBlock(0.3e-3, h, 0.6e-3, er, sigma),
            StubBlock(0.0, 0.3e-3, 0.6e-3, er),  # back-drilled
            ReturnPathBlock(0.3e-3, h, 0.6e-3, er, sigma,
                            d_ret=0.3e-3, s=1.0e-3, d_antipad_ret=0.6e-3),
        ]

        result, report, _ = synthesize_with_discontinuities(
            request, settings,
            right_blocks=right_blocks,
        )

        # Report should include launch/transition section
        text = report.to_text()
        assert "OPTIONAL LAUNCH / TRANSITION CHAIN" in text
        assert "PadBlock" in text
        assert "SignalViaTransitionBlock" in text
        assert "ReturnPathBlock" in text

        d = json.loads(report.to_json())
        assert len(d["blocks"]) == 4
        assert d["blocks"][0]["name"] == "PadBlock"


# ---------------------------------------------------------------------------
# Test: Report content validation
# ---------------------------------------------------------------------------

class TestReportContent:
    """Verify report structure and data integrity."""

    def test_json_round_trip(self, settings):
        """JSON report is valid JSON and contains all sections."""
        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)
        _, report, _ = synthesize_taper(request, settings)

        d = json.loads(report.to_json())

        # Required top-level keys
        required_keys = [
            "report_version", "timestamp", "confidence", "profile",
            "stackup", "analysis", "segmentation", "blocks",
            "model_assumptions", "s_params_summary", "s_params_data",
            "warnings",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

        # S-param data has correct structure
        for point in d["s_params_data"]:
            assert "f_hz" in point
            assert "s11_db" in point
            assert "s21_db" in point

        # Model assumptions are populated
        ma = d["model_assumptions"]
        assert "Hammerstad" in ma["microstrip"]
        assert "Kirschning" in ma["dispersion"]

    def test_text_report_structure(self, settings):
        """Text report has all required sections."""
        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)
        _, report, _ = synthesize_taper(request, settings)

        text = report.to_text()
        required_sections = [
            "TAPER PROFILE",
            "STACKUP",
            "ANALYSIS SETTINGS",
            "SEGMENTATION",
            "MODEL ASSUMPTIONS",
            "S-PARAMETER SUMMARY",
            "S-PARAMETER DATA",
            "END OF REPORT",
        ]
        for section in required_sections:
            assert section in text, f"Missing section: {section}"

    def test_report_save_load(self, settings):
        """Reports save to disk correctly."""
        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)
        _, report, _ = synthesize_taper(request, settings)

        # Use workspace scratch dir
        scratch = os.path.join(os.path.dirname(__file__), "..", "scratch_test")
        os.makedirs(scratch, exist_ok=True)

        txt_path = os.path.join(scratch, "test_report.txt")
        json_path = os.path.join(scratch, "test_report.json")

        report.save_text(txt_path)
        report.save_json(json_path)

        # Verify files exist and are non-empty
        assert os.path.getsize(txt_path) > 100
        assert os.path.getsize(json_path) > 100

        # Verify JSON is parseable
        with open(json_path) as f:
            d = json.load(f)
        assert d["report_version"] == "1.0"

        # Cleanup
        os.remove(txt_path)
        os.remove(json_path)
        os.rmdir(scratch)


# ---------------------------------------------------------------------------
# Test: Settings persistence
# ---------------------------------------------------------------------------

class TestSettingsPersistence:

    def test_settings_round_trip(self):
        """Settings save to JSON and load back identically."""
        s = RFProjectSettings()
        s.stackup.dk_design = 3.66
        s.analysis.f_stop_hz = 30e9
        s.analysis.n_points = 401

        scratch = os.path.join(os.path.dirname(__file__), "..", "scratch_test")
        os.makedirs(scratch, exist_ok=True)
        path = os.path.join(scratch, "test_settings.json")

        import pathlib
        s.save(pathlib.Path(path))
        s2 = RFProjectSettings.load(pathlib.Path(path))

        assert s2.stackup.dk_design == 3.66
        assert s2.analysis.f_stop_hz == 30e9
        assert s2.analysis.n_points == 401

        os.remove(path)
        os.rmdir(scratch)


# ---------------------------------------------------------------------------
# Test: Warning propagation through full chain
# ---------------------------------------------------------------------------

class TestWarningPropagation:

    def test_no_return_via_produces_low_confidence(self, settings, ms):
        """Chain with no return via → low confidence in report."""
        h = settings.stackup.substrate_height_m
        er = settings.stackup.dk_design
        sigma = settings.stackup.conductivity_s_per_m

        request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)

        profile = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.05,
            microstrip=ms, f_min=settings.analysis.f_start_hz,
            f_geom=settings.analysis.f_geom,
        )
        w_end = float(profile.w_profile[-1])

        # Return path block with NO return via
        rp = ReturnPathBlock(0.3e-3, h, 0.6e-3, er, sigma)

        result, report, _ = synthesize_with_discontinuities(
            request, settings,
            right_blocks=[rp],
        )

        # Report should flag low confidence
        d = json.loads(report.to_json())
        assert d["confidence"]["is_low_confidence"] is True

        text = report.to_text()
        assert "LOW CONFIDENCE" in text


# ═══════════════════════════════════════════════════════════════════════
# Live insertion: board-coordinate placement
# ═══════════════════════════════════════════════════════════════════════

class TestLiveInsertion:
    """Test that prepare_insertion generates correctly-placed polygons."""

    def _make_profile(self):
        from rfcore.microstrip import MicrostripModel
        from rfcore.klopfenstein import KlopfensteinProfile

        settings = RFProjectSettings()
        ms = MicrostripModel.from_settings(settings)
        return KlopfensteinProfile(
            ZS=50, ZL=75, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )

    def _make_selection(self, sx_mm, sy_mm, ex_mm, ey_mm,
                        w_start_mm=0.507, w_end_mm=0.220):
        from addon.selection import manual_selection
        return manual_selection(sx_mm, sy_mm, ex_mm, ey_mm,
                                w_start_mm, w_end_mm)

    def test_polygon_anchored_at_start(self):
        """Polygon must start near the selected start point."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(50, 30, 120, 30)  # horizontal
        plan = prepare_insertion(profile, sel, overlap_m=0)

        # First left+right vertices should be at x ≈ 50mm, y ≈ 30mm
        first_left = plan.polygon.left_edge[0]
        first_right = plan.polygon.right_edge[0]
        cx = (first_left[0] + first_right[0]) / 2
        cy = (first_left[1] + first_right[1]) / 2
        assert abs(cx - 0.050) < 1e-6, f"Start X: expected 50mm, got {cx*1e3:.3f}mm"
        assert abs(cy - 0.030) < 1e-6, f"Start Y: expected 30mm, got {cy*1e3:.3f}mm"

    def test_polygon_oriented_toward_end(self):
        """Polygon centerline must point toward the selected end."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        # Horizontal: start (50,30), end (120,30)
        sel = self._make_selection(50, 30, 120, 30)
        plan = prepare_insertion(profile, sel, overlap_m=0)

        # Tangent should be (1, 0) for horizontal
        assert abs(plan.tangent[0] - 1.0) < 1e-6
        assert abs(plan.tangent[1] - 0.0) < 1e-6

        # Last center should be at x > 50mm (progressing rightward)
        last_left = plan.polygon.left_edge[-1]
        last_right = plan.polygon.right_edge[-1]
        end_cx = (last_left[0] + last_right[0]) / 2
        assert end_cx > 0.050, "Polygon should extend rightward"

    def test_polygon_oriented_diagonal(self):
        """Polygon tangent correct for 45-degree diagonal."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        # 45°: start (50,30), end (120,100)
        sel = self._make_selection(50, 30, 120, 100)
        plan = prepare_insertion(profile, sel, overlap_m=0)

        expected_tx = 1.0 / math.sqrt(2)
        expected_ty = 1.0 / math.sqrt(2)
        assert abs(plan.tangent[0] - expected_tx) < 0.01
        assert abs(plan.tangent[1] - expected_ty) < 0.01

    def test_length_is_rf_synthesized(self):
        """Taper length should be profile.L, not gap length."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        # Gap much longer than taper
        sel = self._make_selection(0, 0, 500, 0)
        plan = prepare_insertion(profile, sel)

        assert abs(plan.L_actual_m - profile.L) < 1e-9
        assert plan.L_actual_m < plan.L_gap_m  # gap > taper

    def test_gap_match_detected(self):
        """When gap ≈ L_actual, both endpoints should connect."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        L_mm = profile.L * 1e3
        sel = self._make_selection(50, 30, 50 + L_mm, 30)
        plan = prepare_insertion(profile, sel)

        assert plan.gap_matches
        assert plan.connects_end

    def test_gap_too_short_warning(self):
        """Short gap should warn and not connect end."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(50, 30, 60, 30)  # 10mm gap, way too short
        plan = prepare_insertion(profile, sel)

        assert not plan.connects_end
        assert any("exceeds" in w for w in plan.warnings)

    def test_gap_too_long_warning(self):
        """Long gap should warn and not connect end."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(0, 0, 500, 0)  # 500mm gap
        plan = prepare_insertion(profile, sel)

        assert not plan.connects_end
        assert any("longer than taper" in w for w in plan.warnings)

    def test_overlap_extends_polygon(self):
        """Overlap should add vertices beyond start/end."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        L_mm = profile.L * 1e3
        sel = self._make_selection(50, 30, 50 + L_mm, 30)

        plan_no_overlap = prepare_insertion(profile, sel, overlap_m=0)
        plan_overlap = prepare_insertion(profile, sel, overlap_m=25e-6)

        # With overlap, more vertices
        assert len(plan_overlap.polygon.outline) > len(plan_no_overlap.polygon.outline)

    def test_start_width_matches_profile(self):
        """Layout width at start should match profile."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(50, 30, 120, 30)
        plan = prepare_insertion(profile, sel)

        assert abs(plan.w_start_m - float(profile.w_layout[0])) < 1e-9

    def test_layer_and_net_from_selection(self):
        """Layer and net should come from selection."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(50, 30, 120, 30)
        sel.layer = "B.Cu"
        sel.net_name = "RF_SIG"
        plan = prepare_insertion(profile, sel)

        assert plan.layer == "B.Cu"
        assert plan.net_name == "RF_SIG"

    def test_debug_summary_contains_key_info(self):
        """Debug summary should contain all critical placement data."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(50, 30, 120, 30)
        plan = prepare_insertion(profile, sel)

        summary = plan.debug_summary()
        assert "Start point" in summary
        assert "Predicted end" in summary
        assert "L_gap" in summary
        assert "L_actual" in summary
        assert "BBox" in summary


# ═══════════════════════════════════════════════════════════════════════
# Regression: numpy type coercion in kicad_compat
# ═══════════════════════════════════════════════════════════════════════

class TestKicadCompatCoercion:
    """Ensure kicad_compat unit helpers accept numpy numeric types.

    Unit conversion is now pure Python (no pcbnew.FromMM), so these
    tests run without KiCad.  The key invariant: numpy.float64 inputs
    must produce native Python int outputs.
    """

    def test_from_mm_numpy_float64(self):
        """from_mm must accept np.float64 and return Python int."""
        from addon.kicad_compat import from_mm

        val = np.float64(1.23)
        result = from_mm(val)
        assert isinstance(result, int)
        assert result == 1230000  # 1.23 mm * 1e6

    def test_from_m_numpy_float64(self):
        """from_m must accept np.float64 and return Python int."""
        from addon.kicad_compat import from_m

        val = np.float64(0.00123)  # 1.23 mm
        result = from_m(val)
        assert isinstance(result, int)
        assert result == 1230000  # 0.00123 m * 1e9

    def test_to_mm_returns_float(self):
        """to_mm must return native Python float."""
        from addon.kicad_compat import to_mm

        result = to_mm(1500000)
        assert isinstance(result, float)
        assert result == 1.5

    def test_to_m_returns_float(self):
        """to_m must return native Python float."""
        from addon.kicad_compat import to_m

        result = to_m(1500000000)
        assert isinstance(result, float)
        assert result == 1.5

    def test_roundtrip_mm(self):
        """mm -> IU -> mm must round-trip."""
        from addon.kicad_compat import from_mm, to_mm

        for val in [0.1, 0.507, 1.23, 50.0]:
            iu = from_mm(val)
            back = to_mm(iu)
            assert abs(back - val) < 1e-6, f"Round-trip failed for {val}"

    def test_polygon_coordinates_are_native_float(self):
        """Polygon outline coordinates from numpy arrays must coerce."""
        from rfcore.export.geometry import generate_taper_polygon
        from rfcore.klopfenstein import KlopfensteinProfile
        from rfcore.microstrip import MicrostripModel
        from rfcore.config import RFProjectSettings

        s = RFProjectSettings()
        ms = MicrostripModel.from_settings(s)
        prof = KlopfensteinProfile(
            ZS=50, ZL=75, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        poly = generate_taper_polygon(prof)

        for x, y in poly.outline:
            fx = float(x)
            fy = float(y)
            assert isinstance(fx, float)
            assert isinstance(fy, float)

