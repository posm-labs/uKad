"""Microstrip width-step discontinuity block.

Model: Hammerstad & Kompa excess-fringe capacitance, as documented in
Qucs technical documentation §12.22.  SI units throughout.

For step ratio W1/W2 >= 3, adds series inductance from Garg/Bahl 1978.

Equivalent circuit: shunt capacitance at junction plane (dominant),
plus optional T-network with series L for large step ratios.
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.network import Mat2, abcd_shunt_y, abcd_series_z, abcd_identity
from rfcore.materials_ro4350b import EPS_0


class WidthStepBlock(DiscontinuityBlock):
    """Microstrip width-step discontinuity.

    Parameters
    ----------
    w1 : float
        Wider trace width (m).  Must be > w2.
    w2 : float
        Narrower trace width (m).
    h : float
        Substrate height (m).
    er : float
        Relative permittivity.
    """

    def __init__(self, w1: float, w2: float, h: float, er: float) -> None:
        # Ensure w1 >= w2
        if w1 < w2:
            w1, w2 = w2, w1
        self.w1 = w1
        self.w2 = w2
        self.h = h
        self.er = er

        u1 = w1 / h
        u2 = w2 / h
        self.step_ratio = w1 / w2 if w2 > 0 else float('inf')

        # Hammerstad/Kompa step capacitance (SI)
        # C_step = (ε₀·εr·h/π) · (Δu/(2·u_avg)) · ln(coth(π·Δu/(4·u_avg)))
        du = u1 - u2
        u_avg = (u1 + u2) / 2.0

        if du > 0 and u_avg > 0:
            arg = math.pi * du / (4.0 * u_avg)
            # coth(x) = cosh(x)/sinh(x)
            if arg > 0:
                coth_val = math.cosh(arg) / math.sinh(arg) if arg < 20 else 1.0
                if coth_val > 0:
                    self.C_step = (EPS_0 * er * h / math.pi) * (
                        du / (2.0 * u_avg)
                    ) * math.log(coth_val)
                else:
                    self.C_step = 0.0
            else:
                self.C_step = 0.0
        else:
            self.C_step = 0.0

        # Series inductance for large step ratios (Garg/Bahl approximation)
        # L_s = h · 40.5 · (W1/W2 - 1) / (W1/W2 + 1)^2.2  [nH]
        if self.step_ratio >= 3.0 and w2 > 0:
            r = self.step_ratio
            self.L_step = h * 40.5e-9 * (r - 1.0) / ((r + 1.0) ** 2.2)  # H
        else:
            self.L_step = 0.0

    def abcd(self, f: float) -> Mat2:
        """ABCD matrix at frequency f."""
        omega = 2.0 * math.pi * f

        if self.L_step > 0:
            # T-network: series L/2 — shunt C — series L/2
            z_half = 1j * omega * self.L_step / 2.0
            y_c = 1j * omega * self.C_step
            m = abcd_series_z(z_half) @ abcd_shunt_y(y_c) @ abcd_series_z(z_half)
            return m
        else:
            # Shunt capacitance only
            y_c = 1j * omega * self.C_step
            return abcd_shunt_y(y_c)

    def validate(self) -> List[str]:
        warnings: List[str] = []
        u1 = self.w1 / self.h
        u2 = self.w2 / self.h

        if self.step_ratio >= 10:
            warnings.append(
                f"HIGH: Width step ratio {self.step_ratio:.1f} >= 10. "
                f"Model validity is severely degraded."
            )
        elif self.step_ratio >= 5:
            warnings.append(
                f"WARNING: Width step ratio {self.step_ratio:.1f} >= 5. "
                f"Model accuracy is degraded."
            )

        if u1 > 10 or u2 < 0.1:
            warnings.append(
                f"WARNING: W/h values (u1={u1:.2f}, u2={u2:.2f}) outside "
                f"recommended range [0.1, 10]."
            )
        return warnings

    def params(self) -> Dict:
        return {
            "block": "WidthStep",
            "w1_m": self.w1,
            "w2_m": self.w2,
            "h_m": self.h,
            "er": self.er,
            "C_step_F": self.C_step,
            "L_step_H": self.L_step,
            "step_ratio": self.step_ratio,
        }
