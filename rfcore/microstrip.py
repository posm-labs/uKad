"""Dispersive lossy microstrip transmission line model.

Model stack (all SI units internally):
  Layer 1: Hammerstad–Jensen 1980 quasi-static Zc, εeff (with thickness correction)
  Layer 2: Kirschning–Jansen 1982 dispersion for εeff(f), Zc(f)
  Layer 3: Full Hammerstad CAD-grade conductor loss α_c(w, f)
  Layer 4: Dielectric loss α_d(w, f) with frequency-flat tanδ
  Layer 5: Hammerstad surface roughness correction K_sr (optional)

Numerical conventions:
  - Zc is REAL (loss enters only through complex γ)
  - γ = α + jβ where α = α_c_rough + α_d (Np/m), β = 2πf√εeff/c₀ (rad/m)
  - All inputs/outputs in SI: metres, hertz, S/m, ohms, Np/m, rad/m

Width inversion:
  - Brent's method (scipy.optimize.brentq)
  - Bracket: [w_min=10μm, w_max=50·h]
  - Target function: Zc_static(w) - Z_target = 0

References:
  [1] Hammerstad & Jensen, "Accurate Models for Microstrip CAD," MTT-S 1980.
  [2] Kirschning & Jansen, Electronics Letters, 1982. (εeff dispersion)
  [3] Kirschning & Jansen, IEEE MTT, 1984. (Zc dispersion, R1–R17)
  [4] Gupta, Garg, Chadha, "Computer-Aided Design of Microwave Circuits,"
      Artech House, 1981, Ch.2. (Conductor loss formulas)
  [5] Pozar, "Microwave Engineering," 4th ed., §3.8. (Dielectric loss)
"""

from __future__ import annotations

import math
import numpy as np
from scipy.optimize import brentq

from rfcore.materials_ro4350b import MU_0, EPS_0, C_0, ETA_0


class MicrostripModel:
    """Full dispersive lossy microstrip model for a given stackup.

    Parameters
    ----------
    h : float
        Substrate height (m).
    er : float
        Relative permittivity (design Dk).
    tand : float
        Loss tangent (frequency-flat for v1).
    t : float
        Copper thickness (m).
    sigma : float
        Copper conductivity (S/m).
    roughness : float
        RMS surface roughness (m).  Set to 0 to disable roughness correction.
    """

    # Width inversion bracket
    W_MIN: float = 10.0e-6    # 10 μm
    W_MAX_FACTOR: float = 50.0  # w_max = 50 * h

    def __init__(
        self,
        h: float,
        er: float,
        tand: float,
        t: float,
        sigma: float,
        roughness: float = 0.0,
    ) -> None:
        if h <= 0:
            raise ValueError(f"Substrate height must be positive, got {h}")
        if er <= 1.0:
            raise ValueError(f"εr must be > 1.0, got {er}")
        if sigma <= 0:
            raise ValueError(f"Conductivity must be positive, got {sigma}")

        self.h = h
        self.er = er
        self.tand = tand
        self.t = t
        self.sigma = sigma
        self.roughness = roughness

        self._w_max = self.W_MAX_FACTOR * h

    # -----------------------------------------------------------------------
    # Layer 1: Hammerstad–Jensen 1980 quasi-static
    # -----------------------------------------------------------------------

    def _effective_width(self, w: float) -> float:
        """Compute effective width W_eff with conductor thickness correction.

        ΔW = (t/π)·[1 + ln(4πW/t)]   for W/h ≥ 1/(2π)
        ΔW = (t/π)·[1 + ln(2h/t)]    for W/h < 1/(2π)
        """
        if self.t <= 0:
            return w

        u = w / self.h
        if u >= 1.0 / (2.0 * math.pi):
            # Wide strip
            arg = 4.0 * math.pi * w / self.t
            if arg < 1.0:
                arg = 1.0  # guard log domain
            dw = (self.t / math.pi) * (1.0 + math.log(arg))
        else:
            # Narrow strip
            arg = 2.0 * self.h / self.t
            if arg < 1.0:
                arg = 1.0
            dw = (self.t / math.pi) * (1.0 + math.log(arg))

        return w + dw

    def _zc_eeff_static(self, w: float) -> tuple[float, float]:
        """Quasi-static Zc and εeff using Hammerstad–Jensen 1980.

        Uses thickness-corrected effective width.

        Returns (Zc_static [Ω], εeff_static [dimensionless]).
        """
        w_eff = self._effective_width(w)
        u = w_eff / self.h
        er = self.er

        # F(u) — unified formula valid for all u
        f_u = 6.0 + (2.0 * math.pi - 6.0) * math.exp(
            -((30.666 / u) ** 0.7528)
        )

        # Zc in free space (εr = 1)
        zc_air = (ETA_0 / (2.0 * math.pi)) * math.log(
            f_u / u + math.sqrt(1.0 + (2.0 / u) ** 2)
        )

        # Effective dielectric constant
        a_u = 1.0 + (1.0 / 49.0) * math.log(
            (u ** 4 + (u / 52.0) ** 2) / (u ** 4 + 0.432)
        ) + (1.0 / 18.7) * math.log(1.0 + (u / 18.1) ** 3)

        b_er = 0.564 * ((er - 0.9) / (er + 3.0)) ** 0.053

        eeff = (er + 1.0) / 2.0 + ((er - 1.0) / 2.0) * (
            (1.0 + 10.0 / u) ** (-a_u * b_er)
        )

        # Zc on substrate
        zc = zc_air / math.sqrt(eeff)

        return zc, eeff

    # -----------------------------------------------------------------------
    # Layer 2: Kirschning–Jansen 1982 dispersion
    # -----------------------------------------------------------------------

    def _dispersion_eeff(
        self, w: float, f: float, eeff_static: float
    ) -> float:
        """Frequency-dependent effective dielectric constant.

        Kirschning & Jansen 1982, Electronics Letters.
        Uses f_n = f·h in GHz·mm (converted from Hz·m).
        """
        w_eff = self._effective_width(w)
        u = w_eff / self.h
        er = self.er

        # Convert to GHz·mm
        f_n = f * self.h * 1e-6  # Hz * m * 1e-6 = GHz·mm

        if f_n <= 0:
            return eeff_static

        p1 = 0.27488 + u * (0.6315 + 0.525 / (1.0 + 0.0157 * f_n) ** 20) \
             - 0.065683 * math.exp(-8.7513 * u)
        p2 = 0.33622 * (1.0 - math.exp(-0.03442 * er))
        p3 = 0.0363 * math.exp(-4.6 * u) * (
            1.0 - math.exp(-((f_n / 38.7) ** 4.97))
        )
        p4 = 1.0 + 2.751 * (1.0 - math.exp(-((er / 15.916) ** 8)))

        p_total = p1 * p2 * ((0.1844 + p3 * p4) * f_n) ** 1.5763

        eeff_f = er - (er - eeff_static) / (1.0 + p_total)
        return eeff_f

    def _dispersion_zc(
        self, w: float, f: float, zc_static: float, eeff_static: float,
        eeff_f: float,
    ) -> float:
        """Frequency-dependent characteristic impedance.

        Kirschning & Jansen 1984, IEEE MTT (R1–R17 coefficients).
        """
        w_eff = self._effective_width(w)
        u = w_eff / self.h
        er = self.er
        f_n = f * self.h * 1e-6  # GHz·mm

        if f_n <= 0:
            return zc_static

        r1 = 0.03891 * er ** 1.4
        r2 = 0.267 * u ** 7
        r3 = 4.766 * math.exp(-3.228 * u ** 0.641)
        r4 = 0.016 + (0.0514 * er) ** 4.524
        r5 = (f_n / 28.843) ** 12
        r6 = 22.20 * u ** 1.92

        r7 = 1.206 - 0.3144 * math.exp(-r1) * (1.0 - math.exp(-r2))
        r8 = 1.0 + 1.275 * (
            1.0 - math.exp(
                -0.004625 * r3 * er ** 1.674 * (f_n / 18.365) ** 2.745
            )
        )
        r9_num = 5.086 * r4 * r5
        r9_den = (0.3838 + 0.386 * r4)
        r9 = (r9_num / r9_den) * (math.exp(-r6) / (1.0 + 1.2992 * r5))

        r10 = 0.00044 * er ** 2.136 + 0.0184
        r11_arg = (f_n / 19.47) ** 6
        r11 = r11_arg / (1.0 + 0.0962 * r11_arg)
        r12 = 1.0 / (1.0 + 0.00245 * u ** 2)

        r13 = 0.9408 * eeff_f ** r8 - 0.9603
        r14 = (0.9408 - r9) * eeff_static ** r8 - 0.9603

        r15 = 0.707 * r10 * (f_n / 12.3) ** 1.097
        r16 = 1.0 + 0.0503 * er ** 2 * r11 * (
            1.0 - math.exp(-((u / 3.8) ** 6.2))
        )
        r17 = r7 * (
            1.0 - 1.1241 * r12 / r16
            * math.exp(-0.026 * f_n ** 1.15656 - r15)
        )

        # Guard against division issues
        if abs(r14) < 1e-30:
            return zc_static

        zc_f = zc_static * (r13 / r14) ** r17
        return zc_f

    # -----------------------------------------------------------------------
    # Layer 3: Conductor loss (Hammerstad CAD-grade)
    # -----------------------------------------------------------------------

    def _alpha_c(self, w: float, f: float, zc: float) -> float:
        """Conductor attenuation constant α_c in Np/m.

        Full Hammerstad geometry-dependent model with edge-current correction.
        Separate branches for W/h ≥ 1 and W/h < 1.

        Reference: Gupta/Garg/Chadha Ch.2, synthesized from Hammerstad reports.
        """
        if f <= 0 or self.sigma <= 0:
            return 0.0

        w_eff = self._effective_width(w)
        u = w_eff / self.h
        h = self.h
        t = self.t

        # Surface resistance
        rs = math.sqrt(math.pi * f * MU_0 / self.sigma)

        if t <= 0:
            # Zero-thickness limit: simplified
            return rs / (zc * w_eff)

        if u >= 1.0:
            # Wide strip (W_eff/h ≥ 1)
            # Geometry factor accounts for current crowding at edges
            bracket = 1.0 + h / w_eff + (h / (math.pi * w_eff)) * (
                math.log(2.0 * h / t) + t / w_eff
            )
            if bracket <= 0:
                bracket = 1e-10
            geo_inv = 1.0 / bracket

            # Hammerstad wide-strip correction
            u_sq = u ** 2
            correction = (32.0 - u_sq) / (32.0 + u_sq)

            alpha_c = (rs / (zc * h * 2.0 * math.pi)) * geo_inv * correction
        else:
            # Narrow strip (W_eff/h < 1)
            log_arg = 2.0 * h / t + (t / (2.0 * math.pi * w_eff)) ** 2
            if log_arg < 1.0:
                log_arg = 1.0
            bracket = 1.0 + h / w_eff * (1.0 + (1.0 / math.pi) * math.log(log_arg))
            if bracket <= 0:
                bracket = 1e-10
            geo_inv = 1.0 / bracket

            correction = 1.0 - (u / 4.0) ** 2

            alpha_c = (rs / (zc * h * 2.0 * math.pi)) * geo_inv * correction

        return max(alpha_c, 0.0)

    # -----------------------------------------------------------------------
    # Layer 4: Dielectric loss
    # -----------------------------------------------------------------------

    def _alpha_d(self, f: float, eeff_f: float) -> float:
        """Dielectric attenuation constant α_d in Np/m.

        α_d = k₀·εr·(εeff(f) - 1)·tanδ / (2·√εeff(f)·(εr - 1))

        Reference: Pozar §3.8.
        """
        if f <= 0 or self.tand <= 0:
            return 0.0

        er = self.er
        k0 = 2.0 * math.pi * f / C_0

        if eeff_f <= 1.0:
            eeff_f = 1.0 + 1e-10  # guard
        if er <= 1.0:
            return 0.0

        alpha_d = (k0 * er * (eeff_f - 1.0) * self.tand) / (
            2.0 * math.sqrt(eeff_f) * (er - 1.0)
        )
        return max(alpha_d, 0.0)

    # -----------------------------------------------------------------------
    # Layer 5: Surface roughness correction
    # -----------------------------------------------------------------------

    def _roughness_factor(self, f: float) -> float:
        """Hammerstad surface roughness correction factor K_sr.

        K_sr = 1 + (2/π)·arctan(1.4·(Δ/δs)²)

        Returns 1.0 when roughness is disabled (Δ = 0).
        K_sr → 2 when Δ >> δs (saturates).
        """
        if self.roughness <= 0 or f <= 0:
            return 1.0

        # Skin depth
        delta_s = 1.0 / math.sqrt(math.pi * f * MU_0 * self.sigma)

        ratio = self.roughness / delta_s
        k_sr = 1.0 + (2.0 / math.pi) * math.atan(1.4 * ratio ** 2)
        return k_sr

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def Zc(self, w: float, f: float) -> float:
        """Characteristic impedance (real, ohms) at width w and frequency f."""
        zc_s, eeff_s = self._zc_eeff_static(w)
        eeff_f = self._dispersion_eeff(w, f, eeff_s)
        zc_f = self._dispersion_zc(w, f, zc_s, eeff_s, eeff_f)
        return zc_f

    def Zc_static(self, w: float) -> float:
        """Quasi-static characteristic impedance (no dispersion)."""
        zc_s, _ = self._zc_eeff_static(w)
        return zc_s

    def eeff(self, w: float, f: float) -> float:
        """Effective dielectric constant at width w and frequency f."""
        _, eeff_s = self._zc_eeff_static(w)
        return self._dispersion_eeff(w, f, eeff_s)

    def eeff_static(self, w: float) -> float:
        """Quasi-static effective dielectric constant."""
        _, eeff_s = self._zc_eeff_static(w)
        return eeff_s

    def beta(self, w: float, f: float) -> float:
        """Phase constant β in rad/m."""
        eeff_f = self.eeff(w, f)
        return 2.0 * math.pi * f * math.sqrt(eeff_f) / C_0

    def alpha_c(self, w: float, f: float) -> float:
        """Conductor attenuation α_c in Np/m (includes roughness)."""
        zc_f = self.Zc(w, f)
        ac = self._alpha_c(w, f, zc_f)
        return ac * self._roughness_factor(f)

    def alpha_d(self, w: float, f: float) -> float:
        """Dielectric attenuation α_d in Np/m."""
        eeff_f = self.eeff(w, f)
        return self._alpha_d(f, eeff_f)

    def alpha_total(self, w: float, f: float) -> float:
        """Total attenuation constant α in Np/m."""
        return self.alpha_c(w, f) + self.alpha_d(w, f)

    def gamma(self, w: float, f: float) -> complex:
        """Complex propagation constant γ = α + jβ."""
        a = self.alpha_total(w, f)
        b = self.beta(w, f)
        return complex(a, b)

    # -----------------------------------------------------------------------
    # Width inversion
    # -----------------------------------------------------------------------

    def width_for_Z(self, z_target: float, f: float) -> float:
        """Find strip width w such that Zc(w, f) = z_target.

        Uses Brent's method with bracket [W_MIN, 50·h].
        Zc is monotonically decreasing with w for microstrip.

        Parameters
        ----------
        z_target : float
            Target characteristic impedance (Ω).
        f : float
            Frequency for impedance evaluation (Hz).

        Returns
        -------
        float
            Width in metres.

        Raises
        ------
        ValueError
            If z_target is outside the realizable range.
        """
        w_min = self.W_MIN
        w_max = self._w_max

        z_at_min = self.Zc(w_min, f)
        z_at_max = self.Zc(w_max, f)

        # Zc decreases with w: z_at_min > z_at_max
        if z_at_min < z_at_max:
            # Non-monotonic — should not happen for microstrip
            raise RuntimeError(
                f"Microstrip Zc is not monotonically decreasing with width. "
                f"Zc({w_min*1e6:.1f}μm)={z_at_min:.2f}Ω, "
                f"Zc({w_max*1e6:.1f}μm)={z_at_max:.2f}Ω"
            )

        if z_target > z_at_min:
            raise ValueError(
                f"z_target={z_target:.2f}Ω exceeds maximum realizable impedance "
                f"Zc({w_min*1e6:.1f}μm)={z_at_min:.2f}Ω. "
                f"Narrower trace needed but below minimum width."
            )
        if z_target < z_at_max:
            raise ValueError(
                f"z_target={z_target:.2f}Ω is below minimum realizable impedance "
                f"Zc({w_max*1e6:.1f}μm)={z_at_max:.2f}Ω. "
                f"Wider trace needed but above maximum width."
            )

        def objective(w: float) -> float:
            return self.Zc(w, f) - z_target

        w_solved = brentq(objective, w_min, w_max, xtol=1e-9, rtol=1e-12)

        # Post-check
        z_check = self.Zc(w_solved, f)
        residual = abs(z_check - z_target) / z_target
        if residual > 1e-6:
            raise RuntimeError(
                f"Width inversion residual too large: "
                f"|Zc({w_solved*1e6:.3f}μm) - {z_target:.4f}Ω| / Z_target = {residual:.2e}"
            )

        return w_solved

    def width_for_Z_static(self, z_target: float) -> float:
        """Find width for quasi-static Zc (no dispersion)."""
        w_min = self.W_MIN
        w_max = self._w_max

        z_at_min = self.Zc_static(w_min)
        z_at_max = self.Zc_static(w_max)

        if z_target > z_at_min:
            raise ValueError(
                f"z_target={z_target:.2f}Ω exceeds max static Zc={z_at_min:.2f}Ω"
            )
        if z_target < z_at_max:
            raise ValueError(
                f"z_target={z_target:.2f}Ω below min static Zc={z_at_max:.2f}Ω"
            )

        def objective(w: float) -> float:
            return self.Zc_static(w) - z_target

        return brentq(objective, w_min, w_max, xtol=1e-9, rtol=1e-12)

    # -----------------------------------------------------------------------
    # Convenience: create from RFProjectSettings
    # -----------------------------------------------------------------------

    @classmethod
    def from_settings(cls, settings) -> "MicrostripModel":
        """Create MicrostripModel from an RFProjectSettings object."""
        s = settings.stackup
        return cls(
            h=s.substrate_height_m,
            er=s.dk_design,
            tand=s.df_10ghz,
            t=s.copper_thickness_m,
            sigma=s.conductivity_s_per_m,
            roughness=s.surface_roughness_m,
        )
