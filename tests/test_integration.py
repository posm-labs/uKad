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

        # Report should include block breakdown
        text = report.to_text()
        assert "DISCONTINUITY BLOCKS" in text
        assert "PadBlock" in text
        assert "SignalViaSelfBlock" in text
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
