"""End-to-end integration tests: settings → synthesis → assembly → report.

These tests exercise the full pipeline without a KiCad connection.
"""

import json
import math
import os
import pathlib
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
# One-trace Klopfenstein launch: composite polygon placement
# ═══════════════════════════════════════════════════════════════════════

class TestKlopfensteinLaunch:
    """Test one-trace launch mode: composite polygon in board coordinates."""

    def _make_profile(self):
        from rfcore.microstrip import MicrostripModel
        from rfcore.klopfenstein import KlopfensteinProfile

        settings = RFProjectSettings()
        ms = MicrostripModel.from_settings(settings)
        return KlopfensteinProfile(
            ZS=50, ZL=75, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )

    def _make_selection(self, x_mm=100, y_mm=50,
                        width_mm=0.507, angle_deg=0):
        from addon.selection import manual_selection
        return manual_selection(x_mm, y_mm, width_mm, angle_deg)

    def test_polygon_anchored_at_launch(self):
        """RF body should start at the launch point."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50, angle_deg=0)
        plan = prepare_insertion(profile, sel, overlap_m=0, landing_m=0)

        # First point center should be at (100, 50) mm
        first_left = plan.polygon.left_edge[0]
        first_right = plan.polygon.right_edge[0]
        cx = (first_left[0] + first_right[0]) / 2 * 1e3
        cy = (first_left[1] + first_right[1]) / 2 * 1e3
        assert abs(cx - 100) < 0.01, f"Expected 100mm, got {cx:.3f}mm"
        assert abs(cy - 50) < 0.01, f"Expected 50mm, got {cy:.3f}mm"

    def test_overlap_extends_backward(self):
        """Input overlap should extend backward from launch point."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50, angle_deg=0)
        plan = prepare_insertion(profile, sel, overlap_m=0.001)

        xs = [p[0]*1e3 for p in plan.polygon.outline]
        assert min(xs) < 100, "Overlap should extend backward"

    def test_output_landing_extends_forward(self):
        """Output landing should extend forward from RF body end."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50, angle_deg=0)
        plan = prepare_insertion(profile, sel, landing_m=0.001)

        L_body_mm = profile.L * 1e3
        xs = [p[0]*1e3 for p in plan.polygon.outline]
        assert max(xs) > 100 + L_body_mm, "Landing should extend past body"

    def test_rf_body_length(self):
        """RF body length should equal profile.L."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50)
        plan = prepare_insertion(profile, sel)

        assert abs(plan.L_body_m - profile.L) < 1e-9

    def test_total_length_includes_all_sections(self):
        """Total = overlap + body + landing."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50)
        plan = prepare_insertion(profile, sel, overlap_m=0.001, landing_m=0.002)

        expected = 0.001 + profile.L + 0.002
        assert abs(plan.L_total_m - expected) < 1e-9

    def test_board_coordinates_not_origin(self):
        """Polygon must be in board coordinates, not at origin."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(150, 80, angle_deg=0)
        plan = prepare_insertion(profile, sel)

        xs = [p[0]*1e3 for p in plan.polygon.outline]
        ys = [p[1]*1e3 for p in plan.polygon.outline]
        assert min(xs) > 100, f"BBox x_min={min(xs):.1f} too close to origin"
        assert min(ys) > 70, f"BBox y_min={min(ys):.1f} too close to origin"

    def test_diagonal_direction(self):
        """Polygon should extend in correct diagonal direction."""
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50, angle_deg=45)
        plan = prepare_insertion(profile, sel)

        assert plan.predicted_end_xy_m[0] > 0.100
        assert plan.predicted_end_xy_m[1] > 0.050

    def test_start_width_from_profile(self):
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50)
        plan = prepare_insertion(profile, sel)

        assert abs(plan.w_start_m - float(profile.w_layout[0])) < 1e-9

    def test_end_width_from_profile(self):
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50)
        plan = prepare_insertion(profile, sel)

        assert abs(plan.w_end_m - float(profile.w_layout[-1])) < 1e-9

    def test_layer_from_selection(self):
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50)
        sel.layer = "B.Cu"
        plan = prepare_insertion(profile, sel)

        assert plan.layer == "B.Cu"

    def test_width_mismatch_warning(self):
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50, width_mm=0.200)
        plan = prepare_insertion(profile, sel)

        assert any("differs" in w for w in plan.warnings)

    def test_debug_summary(self):
        from addon.live_insert import prepare_insertion

        profile = self._make_profile()
        sel = self._make_selection(100, 50)
        plan = prepare_insertion(profile, sel)

        summary = plan.debug_summary()
        assert "Launch point" in summary
        assert "L_body" in summary
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


# ═══════════════════════════════════════════════════════════════════════
# Footprint generation
# ═══════════════════════════════════════════════════════════════════════

class TestFootprintGeneration:
    """Test .kicad_mod footprint generation."""

    def _make_spec(self):
        from rfcore.microstrip import MicrostripModel
        from rfcore.klopfenstein import KlopfensteinProfile
        from addon.footprint_gen import FootprintSpec

        ms = MicrostripModel.from_settings(RFProjectSettings())
        profile = KlopfensteinProfile(
            ZS=50, ZL=75, Gamma_m=0.05, microstrip=ms, f_min=1e9)
        return FootprintSpec(profile=profile, fp_name="Test_50_75",
                             ZS=50, ZL=75, Gamma_m=0.05)

    def test_primary_has_custom_pad(self):
        from addon.footprint_gen import generate_footprint
        content = generate_footprint(self._make_spec())
        assert '(pad "1" smd custom' in content
        assert "(gr_poly" in content
        assert "(fill yes)" in content

    def test_primary_has_routing_pad(self):
        from addon.footprint_gen import generate_footprint
        content = generate_footprint(self._make_spec())
        assert '(pad "1" smd rect' in content

    def test_primary_single_pad_name(self):
        """Both pads must use same name '1' for single-net."""
        from addon.footprint_gen import generate_footprint
        content = generate_footprint(self._make_spec())
        assert '(pad "2"' not in content

    def test_debug_has_separate_pads(self):
        from addon.footprint_gen import generate_footprint_debug
        content = generate_footprint_debug(self._make_spec())
        assert '(pad "1" smd rect' in content
        assert '(pad "2" smd rect' in content
        assert "(fp_poly" in content

    def test_metadata_in_descr(self):
        from addon.footprint_gen import generate_footprint
        content = generate_footprint(self._make_spec())
        assert "ZS=50" in content
        assert "ZL=75" in content
        assert "uKad" in content

    def test_save_to_library(self):
        from addon.footprint_gen import generate_footprint, save_footprint
        content = generate_footprint(self._make_spec())
        with tempfile.TemporaryDirectory() as td:
            lib = pathlib.Path(td) / "Test.pretty"
            fp = save_footprint(content, "Test_50_75", lib)
            assert fp.exists()
            assert fp.suffix == ".kicad_mod"
            assert lib.is_dir()

    def test_auto_name(self):
        from addon.footprint_gen import auto_footprint_name
        name = auto_footprint_name(50, 75, 0.05, 1e9)
        assert "50" in name and "75" in name and "1GHz" in name

    def test_dimensions(self):
        from addon.footprint_gen import footprint_dimensions
        dims = footprint_dimensions(self._make_spec())
        assert dims["L_body_mm"] > 0
        assert dims["L_total_mm"] > dims["L_body_mm"]
        assert dims["pad2_x_mm"] > 0

    def test_pad_coordinate_convention(self):
        from addon.footprint_gen import footprint_dimensions
        dims = footprint_dimensions(self._make_spec())
        assert dims["pad1_x_mm"] == 0.0
        expected = (dims["L_landing_start_mm"]/2 + dims["L_body_mm"]
                    + dims["L_landing_end_mm"]/2)
        assert abs(dims["pad2_x_mm"] - expected) < 0.001

    def test_polygon_has_many_vertices(self):
        from addon.footprint_gen import generate_footprint
        content = generate_footprint(self._make_spec())
        assert content.count("(xy ") > 10

