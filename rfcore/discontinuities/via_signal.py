"""Signal via self-block — pi-network model.

Topology:  C_barrel/2  —  (R_barrel + jωL_barrel)  —  C_barrel/2

Barrel inductance: cylindrical inductor (Goldfarb & Pucel 1991)
Barrel resistance: skin-effect on cylindrical barrel
Barrel-antipad capacitance: coaxial approximation

C_barrel = 2π·ε₀·εr·h_barrel / ln(d_antipad / d_finished)
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.network import Mat2, abcd_shunt_y, abcd_series_z
from rfcore.materials_ro4350b import MU_0, EPS_0, C_0


class SignalViaSelfBlock(DiscontinuityBlock):
    """Signal via barrel — pi-network model.

    Parameters
    ----------
    d_finished : float
        Finished via hole diameter (m).
    h_barrel : float
        Barrel length through transition (m).
    d_antipad : float
        Antipad (clearance hole) diameter (m).
    er_fill : float
        Dielectric constant of via fill material.
    sigma : float
        Plating conductivity (S/m).
    """

    def __init__(
        self,
        d_finished: float,
        h_barrel: float,
        d_antipad: float,
        er_fill: float,
        sigma: float,
    ) -> None:
        self.d = d_finished
        self.h = h_barrel
        self.d_antipad = d_antipad
        self.er_fill = er_fill
        self.sigma = sigma

        # Barrel inductance (H)
        ratio = self.d / (2.0 * self.h)
        self.L_barrel = (MU_0 * self.h / (2.0 * math.pi)) * (
            math.log(4.0 * self.h / self.d) + 0.5 * ratio ** 2 - 1.0
        )

        # Barrel-antipad coaxial capacitance (F)
        # Requires d_antipad > d_finished
        if d_antipad > d_finished:
            self.C_barrel = (
                2.0 * math.pi * EPS_0 * er_fill * self.h
                / math.log(d_antipad / d_finished)
            )
        else:
            self.C_barrel = 0.0

    def abcd(self, f: float) -> Mat2:
        """Pi-network: C/2 — series(R+jωL) — C/2."""
        omega = 2.0 * math.pi * f

        # Barrel resistance (skin-effect)
        rs = math.sqrt(math.pi * f * MU_0 / self.sigma) if f > 0 else 0.0
        r_barrel = rs * self.h / (math.pi * self.d)

        # Series impedance
        z_series = r_barrel + 1j * omega * self.L_barrel

        # Shunt admittance (half-capacitance at each end)
        y_half = 1j * omega * self.C_barrel / 2.0

        # Pi-network cascade
        m = abcd_shunt_y(y_half) @ abcd_series_z(z_series) @ abcd_shunt_y(y_half)
        return m

    def validate(self) -> List[str]:
        warnings: List[str] = []

        ratio = self.d_antipad / self.d if self.d > 0 else 0
        if ratio < 1.2:
            warnings.append(
                f"HIGH: d_antipad/d_via = {ratio:.2f} < 1.2. "
                f"Coaxial capacitance approximation breaks down."
            )
        elif ratio < 1.5:
            warnings.append(
                f"WARNING: d_antipad/d_via = {ratio:.2f} < 1.5. "
                f"Coaxial capacitance approximation is degraded."
            )

        if self.h / self.d > 20:
            warnings.append(
                f"WARNING: Via aspect ratio h/d = {self.h/self.d:.1f} > 20."
            )

        return warnings

    def params(self) -> Dict:
        return {
            "block": "SignalViaSelf",
            "d_finished_m": self.d,
            "h_barrel_m": self.h,
            "d_antipad_m": self.d_antipad,
            "er_fill": self.er_fill,
            "sigma_S_per_m": self.sigma,
            "L_barrel_H": self.L_barrel,
            "C_barrel_F": self.C_barrel,
        }
