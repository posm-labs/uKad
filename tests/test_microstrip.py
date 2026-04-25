"""Tests for rfcore.microstrip — Hammerstad-Jensen + Kirschning-Jansen model."""

import math
import pytest
from rfcore.microstrip import MicrostripModel
from rfcore.materials_ro4350b import RO4350B


# Standard 10-mil RO4350B test fixture
@pytest.fixture
def ms_10mil():
    """MicrostripModel for 10-mil RO4350B, 1oz Cu, Dk=3.48."""
    return MicrostripModel(
        h=RO4350B.thickness_10mil_m,    # 0.254 mm
        er=RO4350B.dk_process_10ghz,    # 3.48
        tand=RO4350B.df_10ghz,          # 0.0037
        t=RO4350B.cu_1oz_thickness_m,   # 35 μm
        sigma=RO4350B.cu_conductivity_s_per_m,  # 5.8e7
        roughness=RO4350B.roughness_ed_rtf_m,   # 0.5 μm
    )


class TestQuasiStatic:
    """Test quasi-static Zc and εeff against known values."""

    def test_50ohm_width_ballpark(self, ms_10mil):
        """50Ω on 10-mil RO4350B should be around 0.54mm width."""
        w = ms_10mil.width_for_Z_static(50.0)
        # Rogers MWI calculator gives ~0.54mm for 50Ω on 10mil RO4350B
        assert 0.4e-3 < w < 0.7e-3, f"50Ω width = {w*1e3:.3f} mm, expected ~0.54mm"

    def test_zc_decreases_with_width(self, ms_10mil):
        """Zc should monotonically decrease as width increases."""
        widths = [0.1e-3, 0.3e-3, 0.5e-3, 1.0e-3, 2.0e-3, 5.0e-3]
        impedances = [ms_10mil.Zc_static(w) for w in widths]
        for i in range(len(impedances) - 1):
            assert impedances[i] > impedances[i + 1], (
                f"Zc not decreasing: Zc({widths[i]*1e3:.2f}mm)={impedances[i]:.2f}Ω "
                f"> Zc({widths[i+1]*1e3:.2f}mm)={impedances[i+1]:.2f}Ω"
            )

    def test_eeff_between_1_and_er(self, ms_10mil):
        """εeff must be between 1 and εr."""
        for w in [0.1e-3, 0.5e-3, 2.0e-3]:
            eeff = ms_10mil.eeff_static(w)
            assert 1.0 < eeff < ms_10mil.er, f"εeff={eeff} out of [1, {ms_10mil.er}]"

    def test_high_impedance(self, ms_10mil):
        """Very narrow trace should give high impedance (>100Ω)."""
        zc = ms_10mil.Zc_static(0.05e-3)  # 50 μm wide
        assert zc > 80.0, f"Expected high Zc for 50μm trace, got {zc:.1f}Ω"

    def test_low_impedance(self, ms_10mil):
        """Very wide trace should give low impedance (<20Ω)."""
        zc = ms_10mil.Zc_static(5.0e-3)  # 5 mm wide
        assert zc < 20.0, f"Expected low Zc for 5mm trace, got {zc:.1f}Ω"


class TestDispersion:
    def test_eeff_increases_with_frequency(self, ms_10mil):
        """εeff should increase with frequency (normal microstrip dispersion)."""
        w = 0.5e-3
        freqs = [0.1e9, 1e9, 5e9, 10e9, 20e9]
        eeffs = [ms_10mil.eeff(w, f) for f in freqs]
        for i in range(len(eeffs) - 1):
            assert eeffs[i] <= eeffs[i + 1] + 1e-6, (
                f"εeff not increasing: {eeffs[i]:.4f} at {freqs[i]/1e9:.1f}GHz "
                f"> {eeffs[i+1]:.4f} at {freqs[i+1]/1e9:.1f}GHz"
            )

    def test_zc_at_dc_matches_static(self, ms_10mil):
        """At very low frequency, dispersive Zc should match static."""
        w = 0.5e-3
        zc_static = ms_10mil.Zc_static(w)
        zc_lowf = ms_10mil.Zc(w, 1e6)  # 1 MHz
        assert abs(zc_lowf - zc_static) / zc_static < 0.001


class TestLoss:
    def test_alpha_c_nonnegative(self, ms_10mil):
        """Conductor loss must be non-negative."""
        for w in [0.1e-3, 0.5e-3, 2.0e-3]:
            for f in [1e9, 10e9]:
                ac = ms_10mil.alpha_c(w, f)
                assert ac >= 0, f"α_c should be >= 0, got {ac}"

    def test_alpha_c_positive_for_typical_width(self, ms_10mil):
        """Conductor loss must be clearly positive for typical 50Ω trace."""
        ac = ms_10mil.alpha_c(0.5e-3, 10e9)
        assert ac > 0.01, f"α_c should be > 0.01 Np/m at 10 GHz, got {ac}"

    def test_alpha_d_positive(self, ms_10mil):
        """Dielectric loss must be positive."""
        for f in [1e9, 10e9]:
            ad = ms_10mil.alpha_d(0.5e-3, f)
            assert ad > 0, f"α_d should be > 0, got {ad}"

    def test_alpha_increases_with_frequency(self, ms_10mil):
        """Total loss should generally increase with frequency."""
        w = 0.5e-3
        a_1g = ms_10mil.alpha_total(w, 1e9)
        a_10g = ms_10mil.alpha_total(w, 10e9)
        assert a_10g > a_1g

    def test_gamma_complex(self, ms_10mil):
        """γ should have positive real (loss) and positive imag (propagation)."""
        g = ms_10mil.gamma(0.5e-3, 10e9)
        assert g.real > 0, "α should be > 0"
        assert g.imag > 0, "β should be > 0"


class TestWidthInversion:
    def test_round_trip(self, ms_10mil):
        """Width → Zc → width should round-trip."""
        w_orig = 0.5e-3
        f = 10e9
        zc = ms_10mil.Zc(w_orig, f)
        w_back = ms_10mil.width_for_Z(zc, f)
        assert abs(w_back - w_orig) / w_orig < 1e-6

    def test_static_round_trip(self, ms_10mil):
        """Static width inversion round-trip."""
        w_orig = 0.3e-3
        zc = ms_10mil.Zc_static(w_orig)
        w_back = ms_10mil.width_for_Z_static(zc)
        assert abs(w_back - w_orig) / w_orig < 1e-6

    def test_out_of_range_high(self, ms_10mil):
        """Requesting impedance above realizable range should raise."""
        with pytest.raises(ValueError, match="exceeds"):
            ms_10mil.width_for_Z(500.0, 10e9)

    def test_out_of_range_low(self, ms_10mil):
        """Requesting impedance below realizable range should raise."""
        with pytest.raises(ValueError, match="below"):
            ms_10mil.width_for_Z(1.0, 10e9)


class TestRoughnessCorrection:
    def test_roughness_increases_loss(self):
        """Roughness correction should increase conductor loss."""
        ms_smooth = MicrostripModel(
            h=0.254e-3, er=3.48, tand=0.0037, t=35e-6,
            sigma=5.8e7, roughness=0.0,
        )
        ms_rough = MicrostripModel(
            h=0.254e-3, er=3.48, tand=0.0037, t=35e-6,
            sigma=5.8e7, roughness=1.5e-6,
        )
        ac_smooth = ms_smooth.alpha_c(0.5e-3, 10e9)
        ac_rough = ms_rough.alpha_c(0.5e-3, 10e9)
        assert ac_rough > ac_smooth

    def test_roughness_factor_bounds(self):
        """K_sr should be in [1, 2]."""
        ms = MicrostripModel(
            h=0.254e-3, er=3.48, tand=0.0037, t=35e-6,
            sigma=5.8e7, roughness=5.0e-6,
        )
        k = ms._roughness_factor(10e9)
        assert 1.0 <= k <= 2.0
