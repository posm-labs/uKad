"""Klopfenstein taper profile generation and inverse design.

Implements the classical Klopfenstein 1956 taper with the Kajfez & Prewitt 1973
correction to ρ₀.  Profile is computed in log-impedance space.

References:
  [1] R. W. Klopfenstein, "A Transmission Line Taper of Improved Design,"
      Proc. IRE, vol. 44, pp. 31-35, Jan. 1956.
  [2] D. Kajfez and J. O. Prewitt, "Correction to 'A Transmission Line Taper
      of Improved Design'," IEEE Trans. MTT, vol. 21, no. 5, pp. 364, May 1973.
  [3] M. Steer, "Microwave and RF Design III — Networks," §7.5.

All units SI: impedances in Ω, lengths in m, frequencies in Hz.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from rfcore.microstrip import MicrostripModel


# ---------------------------------------------------------------------------
# φ(w, A) recursion — Steer Eq. 7.5.14
# ---------------------------------------------------------------------------

def _phi(w: float, A: float, k_max: int = 25) -> float:
    """Compute the Klopfenstein taper function φ(w, A).

    Uses the recursion:
        a₀ = 1
        a_k = (A² / (4·k·(k+1))) · a_{k-1}

        b₀ = w/2
        b_k = (w·(1 - w²)^k / 2  +  2·k·b_{k-1}) / (2k + 1)

        φ(w, A) = Σ_{k=0}^{k_max} a_k · b_k

    Properties: φ(-w, A) = -φ(w, A);  φ(0, A) = 0.

    Parameters
    ----------
    w : float
        Normalized position, w = 2z/L, range [-1, +1].
    A : float
        Taper parameter (dimensionless, > 0).
    k_max : int
        Number of terms in the recursion (default 25, sufficient for A ≤ 10).

    Returns
    -------
    float
        φ(w, A).
    """
    # Initialize recursion
    a_k = 1.0
    b_k = w / 2.0
    result = a_k * b_k

    w_sq = w * w
    a_sq = A * A

    for k in range(1, k_max + 1):
        a_k *= a_sq / (4.0 * k * (k + 1))

        # b_k = (w·(1 - w²)^k / 2  +  2·k·b_{k-1}) / (2k + 1)
        power_term = w * ((1.0 - w_sq) ** k) / 2.0
        b_k = (power_term + 2.0 * k * b_k) / (2.0 * k + 1.0)

        result += a_k * b_k

    return result


# ---------------------------------------------------------------------------
# Klopfenstein profile
# ---------------------------------------------------------------------------

class KlopfensteinProfile:
    """Klopfenstein impedance taper profile with width inversion.

    The profile is defined over z ∈ [0, L] (physical coordinates).
    Internally, the Klopfenstein formulas use normalized coordinate
    w = 2z/L - 1 ∈ [-1, +1].

    Parameters
    ----------
    ZS : float
        Start impedance (Ω) at z = 0.
    ZL : float
        End impedance (Ω) at z = L.  Must satisfy ZL ≠ ZS.
    Gamma_m : float
        Maximum passband reflection coefficient magnitude.
    microstrip : MicrostripModel
        Line model for width inversion.
    L : float or None
        Physical taper length (m).  If None, solved from f_min.
    f_min : float or None
        Minimum passband frequency (Hz).  Used in solve-length mode
        and for electrically-short warnings.
    n_samples : int
        Number of z samples for the profile (default 201).
    """

    PHI_K_MAX: int = 25  # recursion depth for φ(w, A)

    def __init__(
        self,
        ZS: float,
        ZL: float,
        Gamma_m: float,
        microstrip: MicrostripModel,
        L: Optional[float] = None,
        f_min: Optional[float] = None,
        f_geom: Optional[float] = None,
        n_samples: int = 201,
    ) -> None:
        if ZS <= 0 or ZL <= 0:
            raise ValueError(f"Impedances must be positive: ZS={ZS}, ZL={ZL}")
        if ZS == ZL:
            raise ValueError("ZS must not equal ZL (no taper needed).")
        if not (0 < Gamma_m < 1):
            raise ValueError(f"Gamma_m must be in (0, 1), got {Gamma_m}")

        self.ZS = ZS
        self.ZL = ZL
        self.Gamma_m = Gamma_m
        self.microstrip = microstrip
        self.f_min = f_min
        self.n_samples = n_samples

        # Geometry-synthesis frequency: defaults to f_min
        self._f_geom = f_geom if f_geom is not None else f_min

        # Kajfez-corrected ρ₀ (1973)
        # ρ₀ = 0.5 * ln(ZL / ZS)
        # (Not the small-reflection approximation (ZL-ZS)/(ZL+ZS))
        self.rho_0 = 0.5 * math.log(self.ZL / self.ZS)

        # Taper parameter A
        # A = acosh(|ρ₀| / Γ_m)
        rho_abs = abs(self.rho_0)
        ratio = rho_abs / self.Gamma_m
        if ratio < 1.0:
            raise ValueError(
                f"Cannot achieve Gamma_m={Gamma_m:.4f} for impedance ratio "
                f"ZL/ZS={ZL/ZS:.3f}.  |ρ₀|={rho_abs:.4f} < Gamma_m.  "
                f"The impedance mismatch is already smaller than the target."
            )
        self.A = math.acosh(ratio)

        # Length
        if L is not None:
            self.L = L
        elif f_min is not None:
            self.L = self.solve_length(f_min)
        else:
            raise ValueError("Either L or f_min must be provided.")

        # Pre-compute profile
        self._z_array = np.linspace(0.0, self.L, self.n_samples)
        self._Z_array = np.array([self.Z_at(z) for z in self._z_array])

        # Width inversion
        if self._f_geom is not None and self._f_geom > 0:
            self._w_array = np.array([
                self.microstrip.width_for_Z(Z, self._f_geom)
                for Z in self._Z_array
            ])
        else:
            self._w_array = np.array([
                self.microstrip.width_for_Z_static(Z)
                for Z in self._Z_array
            ])

    # -----------------------------------------------------------------------
    # Profile computation
    # -----------------------------------------------------------------------

    def Z_at(self, z: float) -> float:
        """Impedance Z(z) at physical position z ∈ [0, L].

        ln(Z(z)) = 0.5·ln(ZS·ZL) + (ρ₀/cosh(A))·A²·φ(2z/L - 1, A)

        At endpoints:
          z = 0 → w = -1 → φ(-1, A) → Z ≈ ZS
          z = L → w = +1 → φ(+1, A) → Z ≈ ZL
        """
        if self.L <= 0:
            return self.ZS

        # Normalized coordinate w ∈ [-1, +1]
        w = 2.0 * z / self.L - 1.0
        w = max(-1.0, min(1.0, w))  # clamp for safety

        phi_val = _phi(w, self.A, self.PHI_K_MAX)

        ln_Z = (0.5 * math.log(self.ZS * self.ZL)
                + (self.rho_0 / math.cosh(self.A)) * self.A ** 2 * phi_val)

        return math.exp(ln_Z)

    def w_at(self, z: float) -> float:
        """Width w(z) at physical position z, via interpolation of pre-computed profile."""
        if z <= 0:
            return self._w_array[0]
        if z >= self.L:
            return self._w_array[-1]

        # Linear interpolation on pre-computed grid
        idx_float = (z / self.L) * (self.n_samples - 1)
        idx_lo = int(idx_float)
        idx_hi = min(idx_lo + 1, self.n_samples - 1)
        frac = idx_float - idx_lo

        return self._w_array[idx_lo] * (1.0 - frac) + self._w_array[idx_hi] * frac

    # -----------------------------------------------------------------------
    # Solve-length mode
    # -----------------------------------------------------------------------

    def solve_length(self, f_min: float) -> float:
        """Compute minimum taper length L for given A and f_min.

        L_min = A / β_eff(f_min)

        where β_eff is evaluated at the geometric-mean impedance width.

        Parameters
        ----------
        f_min : float
            Minimum passband frequency (Hz).

        Returns
        -------
        float
            Minimum taper length L in metres.
        """
        Z_mid = math.sqrt(self.ZS * self.ZL)

        # Get width at geometric-mean impedance
        if self._f_geom is not None and self._f_geom > 0:
            w_mid = self.microstrip.width_for_Z(Z_mid, self._f_geom)
        else:
            w_mid = self.microstrip.width_for_Z_static(Z_mid)

        # Phase constant at f_min
        beta_min = self.microstrip.beta(w_mid, f_min)

        if beta_min <= 0:
            raise ValueError(
                f"Phase constant at f_min={f_min/1e9:.3f} GHz is zero or negative."
            )

        L_min = self.A / beta_min
        return L_min

    # -----------------------------------------------------------------------
    # Properties for external access
    # -----------------------------------------------------------------------

    @property
    def z_samples(self) -> np.ndarray:
        """Position array z ∈ [0, L] in metres."""
        return self._z_array

    @property
    def Z_profile(self) -> np.ndarray:
        """Impedance profile Z(z) in ohms."""
        return self._Z_array

    @property
    def w_profile(self) -> np.ndarray:
        """Width profile w(z) in metres."""
        return self._w_array

    # -----------------------------------------------------------------------
    # Validation / warnings
    # -----------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Check profile validity and return warnings."""
        warnings: list[str] = []

        # Check impedance ratio
        ratio = max(self.ZL, self.ZS) / min(self.ZL, self.ZS)
        if ratio > 100:
            warnings.append(
                f"HIGH: Impedance ratio {ratio:.1f}:1 exceeds recommended limit "
                f"(100:1).  Klopfenstein φ recursion may not converge."
            )
        elif ratio > 50:
            warnings.append(
                f"WARNING: Impedance ratio {ratio:.1f}:1 is high.  "
                f"Verify profile accuracy against reference data."
            )

        # Check A parameter
        if self.A > 10:
            warnings.append(
                f"HIGH: Taper parameter A={self.A:.2f} > 10.  "
                f"φ recursion convergence is not guaranteed."
            )

        # Check monotonicity
        dZ = np.diff(self._Z_array)
        if self.ZL > self.ZS:
            non_mono = np.any(dZ < -1e-10)
        else:
            non_mono = np.any(dZ > 1e-10)

        if non_mono:
            warnings.append(
                "HIGH: Impedance profile is not monotonic.  "
                "This indicates a numerical issue in the φ recursion."
            )

        # Check endpoint accuracy
        z0_err = abs(self._Z_array[0] - self.ZS) / self.ZS
        zL_err = abs(self._Z_array[-1] - self.ZL) / self.ZL
        if z0_err > 0.01:
            warnings.append(
                f"WARNING: Profile start impedance error: "
                f"Z(0)={self._Z_array[0]:.3f}Ω vs ZS={self.ZS:.3f}Ω "
                f"({z0_err*100:.2f}%)."
            )
        if zL_err > 0.01:
            warnings.append(
                f"WARNING: Profile end impedance error: "
                f"Z(L)={self._Z_array[-1]:.3f}Ω vs ZL={self.ZL:.3f}Ω "
                f"({zL_err*100:.2f}%)."
            )

        # Check midpoint
        Z_mid_expected = math.sqrt(self.ZS * self.ZL)
        Z_mid_actual = self.Z_at(self.L / 2.0)
        mid_err = abs(Z_mid_actual - Z_mid_expected) / Z_mid_expected
        if mid_err > 0.001:
            warnings.append(
                f"WARNING: Midpoint impedance error: "
                f"Z(L/2)={Z_mid_actual:.3f}Ω vs √(ZS·ZL)={Z_mid_expected:.3f}Ω "
                f"({mid_err*100:.3f}%)."
            )

        # Electrically short warning
        if self.f_min is not None:
            Z_mid = math.sqrt(self.ZS * self.ZL)
            try:
                w_mid = self.microstrip.width_for_Z(Z_mid, self.f_min)
                beta_min = self.microstrip.beta(w_mid, self.f_min)
                elec_length_deg = (beta_min * self.L) * 180.0 / math.pi
                if elec_length_deg < 30:
                    warnings.append(
                        f"WARNING: Taper is electrically short at f_min: "
                        f"{elec_length_deg:.1f}° (< 30°).  Small-reflection "
                        f"assumption may be inaccurate."
                    )
            except (ValueError, RuntimeError):
                pass

        return warnings
