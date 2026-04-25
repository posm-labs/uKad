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
    def test_endpoints(self, ms):
        """Profile must match ZS at z=0 and ZL at z=L."""
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        Z0 = prof.Z_at(0)
        ZL = prof.Z_at(prof.L)
        # Klopfenstein taper has inherent step discontinuities at endpoints
        # (Steer §7.5). Typical endpoint error is ~5% for moderate impedance ratios.
        assert abs(Z0 - 50.0) / 50.0 < 0.06
        assert abs(ZL - 100.0) / 100.0 < 0.06

    def test_midpoint_geometric_mean(self, ms):
        """Z(L/2) should equal √(ZS·ZL)."""
        ZS, ZL = 50.0, 100.0
        prof = KlopfensteinProfile(
            ZS=ZS, ZL=ZL, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        Z_mid = prof.Z_at(prof.L / 2.0)
        expected = math.sqrt(ZS * ZL)
        assert abs(Z_mid - expected) / expected < 0.001

    def test_monotonic_increasing(self, ms):
        """When ZL > ZS, profile should be monotonically increasing."""
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=100.0, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        Z = prof.Z_profile
        dZ = np.diff(Z)
        assert np.all(dZ >= -1e-10), "Profile is not monotonically increasing"

    def test_monotonic_decreasing(self, ms):
        """When ZL < ZS, profile should be monotonically decreasing."""
        prof = KlopfensteinProfile(
            ZS=100.0, ZL=50.0, Gamma_m=0.05,
            microstrip=ms, f_min=1e9,
        )
        Z = prof.Z_profile
        dZ = np.diff(Z)
        assert np.all(dZ <= 1e-10), "Profile is not monotonically decreasing"

    def test_width_inversion_endpoints(self, ms):
        """Width at endpoints should correspond to ZS and ZL impedances."""
        prof = KlopfensteinProfile(
            ZS=50.0, ZL=75.0, Gamma_m=0.1,
            microstrip=ms, f_min=1e9,
        )
        # Width at start should give Zc ≈ 50Ω
        w_start = prof.w_profile[0]
        zc_start = ms.Zc(w_start, prof._f_geom)
        # Endpoint impedance includes the Klopfenstein step discontinuity effect
        assert abs(zc_start - 50.0) / 50.0 < 0.15

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
