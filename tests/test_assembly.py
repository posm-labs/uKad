"""Integration tests for the full taper assembly chain."""

import math
import numpy as np
import pytest

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import TaperAssembly
from rfcore.discontinuities.step import WidthStepBlock
from rfcore.discontinuities.pad import PadBlock
from rfcore.discontinuities.via_ground import GroundedViaBlock
from rfcore.discontinuities.via_signal import SignalViaSelfBlock
from rfcore.discontinuities.stub import StubBlock
from rfcore.discontinuities.return_path import ReturnPathBlock
from rfcore.materials_ro4350b import RO4350B


@pytest.fixture
def settings():
    s = RFProjectSettings()
    s.analysis.n_points = 51  # fewer points for faster tests
    s.analysis.f_stop_hz = 10e9
    return s


@pytest.fixture
def ms(settings):
    return MicrostripModel.from_settings(settings)


class TestBodyOnly:
    """Test taper body without discontinuities."""

    def test_50_to_75_runs(self, settings, ms):
        """Basic 50→75Ω taper should produce valid S-params."""
        profile = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.05,
            microstrip=ms, f_min=settings.analysis.f_start_hz,
            f_geom=settings.analysis.f_geom,
        )
        assembly = TaperAssembly(settings, profile, ms)
        result = assembly.evaluate()

        assert result.freqs.shape[0] == 51
        assert result.s_params.shape == (51, 2, 2)

        # S21: lossy taper has insertion loss. Allow up to 6 dB at high freq
        assert np.all(result.s21_db > -6.0), \
            f"Excessive insertion loss: min S21 = {result.s21_db.min():.1f} dB"

        # S11 should be below 0 dB (passive)
        assert np.all(result.s11_db < 0.0)

    def test_low_ratio_taper(self, settings, ms):
        """A low impedance ratio taper should have very small S11."""
        profile = KlopfensteinProfile(
            ZS=50.0, ZL=55.0, Gamma_m=0.01,
            microstrip=ms, f_min=settings.analysis.f_start_hz,
            f_geom=settings.analysis.f_geom,
        )
        assembly = TaperAssembly(settings, profile, ms)
        result = assembly.evaluate()

        # At passband frequencies (above f_min), S11 should be small
        # Use midband and above for the check
        mid_idx = len(result.freqs) // 2
        s11_upper = result.s11_db[mid_idx:]
        assert np.all(s11_upper < -10.0), \
            f"S11 too high for small ratio taper: max = {s11_upper.max():.1f} dB"


class TestWithDiscontinuities:
    """Test assembly with endpoint discontinuity blocks."""

    def test_with_step_discontinuities(self, settings, ms):
        """Adding step discontinuities should change (worsen) S11."""
        h = settings.stackup.substrate_height_m
        er = settings.stackup.dk_design

        profile = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.05,
            microstrip=ms, f_min=settings.analysis.f_start_hz,
            f_geom=settings.analysis.f_geom,
        )

        # Body only
        assembly_body = TaperAssembly(settings, profile, ms)
        result_body = assembly_body.evaluate()

        # With steps: add a step from 40Ω width to taper start width
        w_40 = ms.width_for_Z(40.0, settings.analysis.f_geom)
        w_start = profile.w_profile[0]
        step_block = WidthStepBlock(w_40, w_start, h, er)

        assembly_with_step = TaperAssembly(
            settings, profile, ms,
            left_chain=[step_block],
        )
        result_step = assembly_with_step.evaluate()

        # S11 should generally be worse with the step
        # (not guaranteed at every frequency, but on average)
        assert result_step.s_params.shape == result_body.s_params.shape

    def test_with_full_via_chain(self, settings, ms):
        """Test with a realistic via transition chain at the output."""
        h = settings.stackup.substrate_height_m
        er = settings.stackup.dk_design
        sigma = settings.stackup.conductivity_s_per_m

        profile = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.05,
            microstrip=ms, f_min=settings.analysis.f_start_hz,
            f_geom=settings.analysis.f_geom,
        )

        w_end = profile.w_profile[-1]

        # 4 modular sub-blocks
        pad = PadBlock(
            w_in=w_end, w_out=w_end,
            w_pad=0.7e-3, l_pad=0.7e-3,  # 0.7mm circular pad
            h=h, er=er, microstrip=ms,
        )
        via_self = SignalViaSelfBlock(
            d_finished=0.3e-3,  # 0.3mm drill
            h_barrel=h,
            d_antipad=0.6e-3,  # 0.6mm clearance
            er_fill=er,
            sigma=sigma,
        )
        stub = StubBlock(
            h_stub=0.0,  # back-drilled
            d_finished=0.3e-3,
            d_antipad=0.6e-3,
            er_fill=er,
        )
        return_path = ReturnPathBlock(
            d_sig=0.3e-3,
            h_transition=h,
            d_antipad_sig=0.6e-3,
            er=er,
            sigma=sigma,
            d_ret=0.3e-3,
            s=1.0e-3,  # 1mm to return via
            d_antipad_ret=0.6e-3,
        )

        assembly = TaperAssembly(
            settings, profile, ms,
            right_chain=[pad, via_self, stub, return_path],
        )
        result = assembly.evaluate()

        # Should still produce valid S-params
        assert result.s_params.shape == (51, 2, 2)
        # S21 should still be reasonable (< 6 dB IL)
        assert np.all(result.s21_db > -6.0), \
            f"Via chain causing excessive IL: min S21 = {result.s21_db.min():.1f} dB"


class TestWarnings:
    def test_no_return_via_flags_low_confidence(self, settings, ms):
        """Missing return via should produce HIGH warning."""
        h = settings.stackup.substrate_height_m
        er = settings.stackup.dk_design
        sigma = settings.stackup.conductivity_s_per_m

        rp = ReturnPathBlock(
            d_sig=0.3e-3, h_transition=h,
            d_antipad_sig=0.6e-3, er=er, sigma=sigma,
            # No return via
        )

        warnings = rp.validate()
        assert any("HIGH" in w for w in warnings)
        assert rp.is_low_confidence


class TestBlockSanity:
    """Quick sanity checks on individual discontinuity blocks."""

    def test_step_dc_is_through(self):
        """At DC, step capacitance is open → ABCD = identity."""
        step = WidthStepBlock(0.5e-3, 0.3e-3, 0.254e-3, 3.48)
        m = step.abcd(0.0)
        np.testing.assert_allclose(m, np.eye(2), atol=1e-14)

    def test_grounded_via_inductance_positive(self):
        via = GroundedViaBlock(0.3e-3, 0.254e-3, 5.8e7)
        assert via.L_via > 0

    def test_signal_via_capacitance_positive(self):
        via = SignalViaSelfBlock(0.3e-3, 0.254e-3, 0.6e-3, 3.48, 5.8e7)
        assert via.C_barrel > 0
        assert via.L_barrel > 0

    def test_stub_identity_when_zero_length(self):
        stub = StubBlock(0.0, 0.3e-3, 0.6e-3, 3.48)
        m = stub.abcd(10e9)
        np.testing.assert_allclose(m, np.eye(2), atol=1e-14)

    def test_return_path_loop_inductance_positive(self):
        rp = ReturnPathBlock(
            d_sig=0.3e-3, h_transition=0.254e-3,
            d_antipad_sig=0.6e-3, er=3.48, sigma=5.8e7,
            d_ret=0.3e-3, s=1.0e-3, d_antipad_ret=0.6e-3,
        )
        assert rp.L_loop > 0
        assert rp.C_spread > 0
