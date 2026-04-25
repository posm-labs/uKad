"""Open stub block — unused via barrel below exit layer.

Models the unused portion of a via barrel as an open-ended coaxial stub.
The stub presents a shunt admittance at the transition point.

Y_stub(f) = (1/Z_stub) · tanh(γ_stub · h_stub)

where Z_stub is the coaxial characteristic impedance and γ_stub is the
propagation constant (lossless for v1).

If h_stub = 0 (back-drilled or no stub), the block is an identity.
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.network import Mat2, abcd_shunt_y, abcd_identity
from rfcore.materials_ro4350b import MU_0, EPS_0, C_0


class StubBlock(DiscontinuityBlock):
    """Open via barrel stub.

    Parameters
    ----------
    h_stub : float
        Stub length (m).  0 if back-drilled.
    d_finished : float
        Via finished hole diameter (m).
    d_antipad : float
        Antipad diameter (m).
    er_fill : float
        Dielectric constant of fill material.
    """

    def __init__(
        self,
        h_stub: float,
        d_finished: float,
        d_antipad: float,
        er_fill: float,
    ) -> None:
        self.h_stub = h_stub
        self.d = d_finished
        self.d_antipad = d_antipad
        self.er_fill = er_fill

        # Coaxial characteristic impedance
        # Z_stub = (1/(2π)) · √(μ₀/(ε₀·εr)) · ln(d_antipad/d_finished)
        if d_antipad > d_finished and d_finished > 0:
            self.Z_stub = (1.0 / (2.0 * math.pi)) * math.sqrt(
                MU_0 / (EPS_0 * er_fill)
            ) * math.log(d_antipad / d_finished)
        else:
            self.Z_stub = 50.0  # fallback, will be flagged by validate()

    def abcd(self, f: float) -> Mat2:
        if self.h_stub <= 0:
            return abcd_identity()

        omega = 2.0 * math.pi * f

        # Lossless coaxial propagation constant (v1)
        # γ_stub = jβ = j·2πf·√(ε₀·εr·μ₀) = j·2πf·√εr/c₀
        beta = 2.0 * math.pi * f * math.sqrt(self.er_fill) / C_0
        gamma_l = 1j * beta * self.h_stub

        # Open-stub input admittance: Y = (1/Z) · tanh(γl)
        y_stub = np.tanh(gamma_l) / self.Z_stub

        return abcd_shunt_y(y_stub)

    def validate(self) -> List[str]:
        warnings: List[str] = []
        if self.h_stub <= 0:
            return warnings

        # Check if stub can cause in-band resonance
        # Quarter-wave resonance at f_res = c₀ / (4·h_stub·√εr)
        f_res = C_0 / (4.0 * self.h_stub * math.sqrt(self.er_fill))
        warnings.append(
            f"INFO: Open stub present (h_stub={self.h_stub*1e6:.0f} μm). "
            f"Quarter-wave resonance at ~{f_res/1e9:.2f} GHz."
        )

        # Electrical length check would require knowing f_stop
        # We flag based on geometry
        if self.d_antipad <= self.d:
            warnings.append(
                f"HIGH: d_antipad ({self.d_antipad*1e6:.0f} μm) <= d_via "
                f"({self.d*1e6:.0f} μm). Coaxial model invalid."
            )

        return warnings

    def params(self) -> Dict:
        return {
            "block": "Stub",
            "h_stub_m": self.h_stub,
            "d_finished_m": self.d,
            "d_antipad_m": self.d_antipad,
            "er_fill": self.er_fill,
            "Z_stub_ohm": self.Z_stub,
        }
