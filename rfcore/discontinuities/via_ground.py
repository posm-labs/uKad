"""Grounded via discontinuity block.

Model: cylindrical inductor + skin-effect barrel resistance, shunt to ground.

L_via = (μ₀·h/(2π))·[ln(4h/d) + 0.5·(d/(2h))² - 1]
R_via(f) = Rs(f)·h/(π·d)
Z_via = R_via + jωL_via

ABCD = [[1, 0], [1/Z_via, 1]]   (shunt element)

Reference: Goldfarb & Pucel, IEEE MGWL, 1991.
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.network import Mat2, abcd_shunt_y
from rfcore.materials_ro4350b import MU_0, C_0


class GroundedViaBlock(DiscontinuityBlock):
    """Grounded via (shunt to ground).

    Parameters
    ----------
    d_finished : float
        Finished hole diameter (m).
    h_barrel : float
        Barrel length through substrate (m).
    sigma : float
        Plating conductivity (S/m).
    er : float
        Dielectric constant (for wavelength checks).
    """

    def __init__(
        self,
        d_finished: float,
        h_barrel: float,
        sigma: float,
        er: float = 3.48,
    ) -> None:
        self.d = d_finished
        self.h = h_barrel
        self.sigma = sigma
        self.er = er

        # Via inductance (H)
        d = self.d
        h = self.h
        ratio = d / (2.0 * h)
        self.L_via = (MU_0 * h / (2.0 * math.pi)) * (
            math.log(4.0 * h / d) + 0.5 * ratio ** 2 - 1.0
        )

    def abcd(self, f: float) -> Mat2:
        omega = 2.0 * math.pi * f

        # Skin-effect barrel resistance
        rs = math.sqrt(math.pi * f * MU_0 / self.sigma) if f > 0 else 0.0
        r_via = rs * self.h / (math.pi * self.d)

        z_via = r_via + 1j * omega * self.L_via
        y_via = 1.0 / z_via if abs(z_via) > 1e-30 else 1e30 + 0j

        return abcd_shunt_y(y_via)

    def validate(self) -> List[str]:
        warnings: List[str] = []
        # Check electrical length
        # λ in dielectric ≈ c₀/(f·√εr), but we don't know f here.
        # Report geometric ratio instead.
        if self.h / self.d > 20:
            warnings.append(
                f"WARNING: Via aspect ratio h/d = {self.h/self.d:.1f} > 20. "
                f"Cylindrical model may be inaccurate."
            )
        return warnings

    def params(self) -> Dict:
        return {
            "block": "GroundedVia",
            "d_finished_m": self.d,
            "h_barrel_m": self.h,
            "sigma_S_per_m": self.sigma,
            "L_via_H": self.L_via,
        }
