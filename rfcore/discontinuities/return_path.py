"""Return-path transition block — fast two-port approximation.

Classification: Fast lumped/semi-lumped two-port transition-environment
approximation for return-current plane transfer.

NOT a substitute for EM when spreading/cavity effects dominate.

The model captures:
  - Loop inductance between signal and return via (parallel-cylinder mutual L)
  - Return-via barrel resistance (skin-effect)
  - Local inter-plane capacitance near the transition (spreading capacitance)

The model does NOT capture:
  - Plane-cavity resonances
  - Distributed spreading resistance in the reference plane
  - Multi-via return-current splitting
  - Slot effects in the reference plane
  - Via-to-via coupling beyond nearest return via

Two operating modes:
  Case 1: Return via present → T-network: (R+jωL)/2 — jωC — (R+jωL)/2
  Case 2: No return via → series spreading inductance + LOW CONFIDENCE warning

Reference: L_mutual from Grover "Inductance Calculations" 1946 (parallel cylinders).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.network import Mat2, abcd_series_z, abcd_shunt_y, abcd_identity
from rfcore.materials_ro4350b import MU_0, EPS_0, C_0


class ReturnPathBlock(DiscontinuityBlock):
    """Return-path transition block.

    Parameters
    ----------
    d_sig : float
        Signal via finished diameter (m).
    d_ret : float or None
        Return via finished diameter (m).  None if no return via.
    s : float or None
        Center-to-center separation, signal to return via (m).
    h_transition : float
        Vertical distance between reference planes (m).
    d_antipad_sig : float
        Signal via antipad diameter (m).
    d_antipad_ret : float or None
        Return via antipad diameter (m).
    er : float
        Dielectric constant between planes.
    sigma : float
        Copper conductivity (S/m).
    """

    # Spreading radius heuristic when no return via
    SPREADING_FACTOR: float = 10.0

    def __init__(
        self,
        d_sig: float,
        h_transition: float,
        d_antipad_sig: float,
        er: float,
        sigma: float,
        d_ret: Optional[float] = None,
        s: Optional[float] = None,
        d_antipad_ret: Optional[float] = None,
    ) -> None:
        self.d_sig = d_sig
        self.d_ret = d_ret
        self.s = s
        self.h_transition = h_transition
        self.d_antipad_sig = d_antipad_sig
        self.d_antipad_ret = d_antipad_ret
        self.er = er
        self.sigma = sigma

        self.has_return_via = (d_ret is not None and s is not None and s > 0)

        if self.has_return_via:
            # Loop inductance (parallel-cylinder mutual inductance, Grover 1946)
            # L_mutual = (μ₀·h/(2π)) · ln(s / √(d_sig·d_ret/4))
            gmr = math.sqrt(d_sig * d_ret / 4.0)
            if s > gmr:
                self.L_loop = (MU_0 * h_transition / (2.0 * math.pi)) * math.log(s / gmr)
            else:
                self.L_loop = 0.0

            # Return via self-inductance (for R calculation)
            d_r = d_ret
            ratio = d_r / (2.0 * h_transition)
            self.L_ret_self = (MU_0 * h_transition / (2.0 * math.pi)) * (
                math.log(4.0 * h_transition / d_r) + 0.5 * ratio ** 2 - 1.0
            )

            # Plane-spreading capacitance (parallel-plate approximation)
            d_min = min(d_antipad_sig, d_antipad_ret or d_antipad_sig)
            self.C_spread = EPS_0 * er * math.pi * d_min ** 2 / (4.0 * h_transition)

        else:
            # No return via — spreading model
            s_spread = self.SPREADING_FACTOR * h_transition
            self.L_spread = (MU_0 * h_transition / (2.0 * math.pi)) * math.log(
                2.0 * s_spread / d_sig
            )
            self.L_loop = 0.0
            self.L_ret_self = 0.0
            self.C_spread = 0.0

    def abcd(self, f: float) -> Mat2:
        omega = 2.0 * math.pi * f

        if self.has_return_via:
            # Return via barrel resistance (skin-effect)
            rs = math.sqrt(math.pi * f * MU_0 / self.sigma) if f > 0 else 0.0
            r_ret = rs * self.h_transition / (math.pi * self.d_ret)

            # T-network: (R+jωL)/2 — jωC — (R+jωL)/2
            z_series_half = (r_ret + 1j * omega * self.L_loop) / 2.0
            y_shunt = 1j * omega * self.C_spread

            m = (abcd_series_z(z_series_half)
                 @ abcd_shunt_y(y_shunt)
                 @ abcd_series_z(z_series_half))
            return m
        else:
            # No return via: series spreading inductance only
            z_spread = 1j * omega * self.L_spread
            return abcd_series_z(z_spread)

    def validate(self) -> List[str]:
        warnings: List[str] = []

        if not self.has_return_via:
            warnings.append(
                "HIGH: No return via identified for reference-plane transition. "
                "Return current must spread through plane cavity. "
                "Fast model uses spreading inductance estimate (low confidence). "
                "EM validation strongly recommended."
            )
            return warnings

        # Check s/h ratio
        s_h = self.s / self.h_transition if self.h_transition > 0 else 0
        if s_h > 50:
            warnings.append(
                f"HIGH: Return via distance s/h = {s_h:.1f} > 50. "
                f"Model is outside valid regime. Using spreading model."
            )
        elif s_h > 20:
            warnings.append(
                f"WARNING: Return via distance s/h = {s_h:.1f} > 20. "
                f"Near-field mutual inductance model is degraded."
            )

        # Check transition electrical length (need f_stop for proper check)
        # Warn based on geometry
        if self.h_transition > 2e-3:  # > 2mm
            warnings.append(
                f"WARNING: h_transition = {self.h_transition*1e3:.2f} mm is large. "
                f"Verify lumped model validity at your frequency range."
            )

        return warnings

    @property
    def is_low_confidence(self) -> bool:
        """True if this block should flag the entire chain as low-confidence."""
        if not self.has_return_via:
            return True
        s_h = self.s / self.h_transition if self.h_transition > 0 else 0
        return s_h > 50

    def params(self) -> Dict:
        d: Dict = {
            "block": "ReturnPath",
            "d_sig_m": self.d_sig,
            "h_transition_m": self.h_transition,
            "d_antipad_sig_m": self.d_antipad_sig,
            "er": self.er,
            "has_return_via": self.has_return_via,
        }
        if self.has_return_via:
            d.update({
                "d_ret_m": self.d_ret,
                "s_m": self.s,
                "d_antipad_ret_m": self.d_antipad_ret,
                "L_loop_H": self.L_loop,
                "C_spread_F": self.C_spread,
            })
        else:
            d["L_spread_H"] = self.L_spread
        return d
