"""Tests for rfcore.klopfenstein — Klopfenstein taper profile."""

import math
import numpy as np
import pytest
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile, _phi
from rfcore.materials_ro4350b import RO4350B


@pytest.fixture
def ms():
    return MicrostripModel(
        h=RO4350B.thickness_10mil_m,
        er=RO4350B.dk_process_10ghz,
        tand=RO4350B.df_10ghz,
        t=RO4350B.cu_1oz_thickness_m,
        sigma=RO4350B.cu_conductivity_s_per_m,
        roughness=0.0,
    )


class TestPhi:
    def test_phi_zero_at_origin(self):
        """φ(0, A) = 0 for any A."""
        for A in [0.5, 1.0, 2.0, 5.0]:
            assert abs(_phi(0.0, A)) < 1e-14

    def test_phi_antisymmetric(self):
        """φ(-w, A) = -φ(w, A)."""
        for A in [1.0, 2.72, 5.0]:
            for w in [0.1, 0.3, 0.5, 0.8, 1.0]:
                p_pos = _phi(w, A)
                p_neg = _phi(-w, A)
                assert abs(p_pos + p_neg) < 1e-12, (
                    f"φ({w}, {A}) = {p_pos}, φ({-w}, {A}) = {p_neg}"
                )

    def test_phi_convergence(self):
        """φ should converge: adding more terms should not change result much."""
        A = 2.72
        w = 0.5
        phi_20 = _phi(w, A, k_max=20)
        phi_25 = _phi(w, A, k_max=25)
        phi_30 = _phi(w, A, k_max=30)
        assert abs(phi_25 - phi_20) < 1e-10
        assert abs(phi_30 - phi_25) < 1e-14


class TestKlopfensteinProfile:
    def test_endpoints_raw_profile_has_gamma_m_steps(self, ms):
        """Raw Klopfenstein profile has inherent endpoint steps = Γm."""
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        # Raw profile endpoint step = ρ₀/cosh(A) = Γm exactly
        assert abs(prof.endpoint_step_ln - 0.05) < 1e-10
        # Z(0) = ZS·exp(+Γm), Z(L) = ZL·exp(-Γm)
        Z0_expected = 50.0 * math.exp(0.05)
        ZL_expected = 100.0 * math.exp(-0.05)
        assert abs(prof.Z_raw_start - Z0_expected) / Z0_expected < 1e-6
        assert abs(prof.Z_raw_end - ZL_expected) / ZL_expected < 1e-6

    def test_layout_profile_endpoints_exact(self, ms):
        """Layout width profile has endpoints clamped to exact ZS/ZL."""
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        # Layout widths at endpoints should correspond to exactly ZS and ZL
        w_layout_start = prof.w_layout[0]
        w_layout_end = prof.w_layout[-1]
        zc_start = ms.Zc(w_layout_start, prof._f_geom)
        zc_end = ms.Zc(w_layout_end, prof._f_geom)
        assert abs(zc_start - 50.0) / 50.0 < 1e-6
        assert abs(zc_end - 100.0) / 100.0 < 1e-6

    def test_fixed_length_mode(self, ms):
        """Fixed-length mode should use the given L."""
        L_fixed = 10e-3  # 10 mm
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.05,
            microstrip=ms, L=L_fixed, f_min=1e9,
        )
        assert prof.L == L_fixed

    def test_solve_length_smaller_gamma_m_gives_longer_taper(self, ms):
        """Tighter Gamma_m should require longer taper."""
        prof1 = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.1,
            microstrip=ms, f_min=1e9,
        )
        prof2 = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.03,
            microstrip=ms, f_min=1e9,
        )
        assert prof2.L > prof1.L

    def test_equal_impedances_raises(self, ms):
        with pytest.raises(ValueError, match="must not equal"):
            KlopfensteinProfile(ZS=50.0, ZL=50.0, Gamma_m=0.05,
                                microstrip=ms, f_min=1e9)

    def test_gamma_m_too_large_raises(self, ms):
        """If Gamma_m > |ρ₀|, no taper is needed — should raise."""
        with pytest.raises(ValueError, match="already smaller"):
            KlopfensteinProfile(ZS=50.0, ZL=51.0, Gamma_m=0.5,
                                microstrip=ms, f_min=1e9)

    def test_validate_clean(self, ms):
        """A well-formed profile should produce no high-severity warnings."""
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        warnings = prof.validate()
        high = [w for w in warnings if w.startswith("HIGH")]
        assert len(high) == 0, f"Unexpected high warnings: {high}"
