"""Landing section discontinuity block.

Models a constant-width microstrip transmission line section used as
a routing landing at the input or output of the taper.

This is an additive wrapper — no existing RF code is modified.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.microstrip import MicrostripModel
from rfcore.network import Mat2, abcd_tline, abcd_identity


class LandingBlock(DiscontinuityBlock):
    """Constant-width microstrip transmission line section.

    Models the straight landing pad as a lossy transmission line
    with characteristic impedance Zc(w, f) and propagation constant
    γ(w, f) at the landing width.

    Parameters
    ----------
    width_m : float
        Strip width in metres (w_start or w_end).
    length_m : float
        Landing length in metres.
    microstrip : MicrostripModel
        Microstrip model for Zc and γ computation.
    label : str
        Human-readable label ("input_landing" or "output_landing").
    """

    def __init__(self, width_m: float, length_m: float,
                 microstrip: MicrostripModel, label: str = "landing"):
        self._width = width_m
        self._length = length_m
        self._microstrip = microstrip
        self._label = label

    def abcd(self, f: float) -> Mat2:
        """ABCD matrix at frequency f."""
        if self._length <= 0:
            return abcd_identity()

        zc = self._microstrip.Zc(self._width, f)
        gamma = self._microstrip.gamma(self._width, f)
        gamma_l = gamma * self._length
        return abcd_tline(zc, gamma_l)

    def validate(self) -> List[str]:
        warnings: List[str] = []
        if self._length < 0:
            warnings.append(f"WARNING: {self._label} length is negative.")
        if self._width <= 0:
            warnings.append(f"WARNING: {self._label} width is non-positive.")
        return warnings

    def params(self) -> Dict:
        return {
            "type": "LandingBlock",
            "label": self._label,
            "width_m": self._width,
            "length_m": self._length,
        }

    @property
    def name(self) -> str:
        return self._label
