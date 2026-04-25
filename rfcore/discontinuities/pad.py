"""Pad discontinuity block — excess-metal transition capacitance.

The pad is modeled as a short wider microstrip section flanked by two
width-step discontinuities.  This captures excess capacitance from the
wider metal, conductor loss in pad copper, and dispersion.

No antipad correction is applied here; the antipad effect is captured
solely by the coaxial barrel-antipad capacitance in the signal-via self block.
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.discontinuities.step import WidthStepBlock
from rfcore.microstrip import MicrostripModel
from rfcore.network import Mat2, abcd_tline, abcd_identity


class PadBlock(DiscontinuityBlock):
    """Pad / widened-flare discontinuity block.

    Parameters
    ----------
    w_in : float
        Trace width entering pad (m).
    w_out : float
        Trace width exiting pad (m).
    w_pad : float
        Pad width (m).  For circular pad, use diameter.
    l_pad : float
        Pad extent along trace axis (m).  For circular pad, use diameter.
    h : float
        Substrate height (m).
    er : float
        Relative permittivity.
    microstrip : MicrostripModel
        Line model for evaluating the wider section.
    """

    def __init__(
        self,
        w_in: float,
        w_out: float,
        w_pad: float,
        l_pad: float,
        h: float,
        er: float,
        microstrip: MicrostripModel,
    ) -> None:
        self.w_in = w_in
        self.w_out = w_out
        self.w_pad = w_pad
        self.l_pad = l_pad
        self.h = h
        self.er = er
        self.microstrip = microstrip

        # Create width-step blocks at pad edges
        self.step_in = WidthStepBlock(w_in, w_pad, h, er)
        self.step_out = WidthStepBlock(w_pad, w_out, h, er)

    def abcd(self, f: float) -> Mat2:
        """ABCD = step_in · lossy_tline(w_pad, l_pad) · step_out."""
        # Lossy transmission line section at pad width
        zc = self.microstrip.Zc(self.w_pad, f)
        gamma = self.microstrip.gamma(self.w_pad, f)
        gamma_l = gamma * self.l_pad

        m_step_in = self.step_in.abcd(f)
        m_tline = abcd_tline(zc, gamma_l)
        m_step_out = self.step_out.abcd(f)

        return m_step_in @ m_tline @ m_step_out

    def validate(self) -> List[str]:
        warnings: List[str] = []

        # Pad dimension checks
        ratio_l = self.l_pad / self.h
        ratio_w = self.w_pad / max(self.w_in, self.w_out)

        if ratio_l >= 20:
            warnings.append(
                f"HIGH: Pad length/h = {ratio_l:.1f} >= 20. "
                f"This is a transmission line section, not a pad."
            )
        elif ratio_l >= 10:
            warnings.append(
                f"WARNING: Pad length/h = {ratio_l:.1f} >= 10. "
                f"Pad model confidence is degraded."
            )

        if ratio_w >= 10:
            warnings.append(
                f"WARNING: Pad width/trace width = {ratio_w:.1f} >= 10. "
                f"Step model accuracy is degraded."
            )

        if self.l_pad < self.microstrip.t:
            warnings.append(
                f"WARNING: Pad length ({self.l_pad*1e6:.1f} μm) < copper "
                f"thickness ({self.microstrip.t*1e6:.1f} μm). Model may not apply."
            )

        # Cascade sub-block warnings
        warnings.extend(self.step_in.validate())
        warnings.extend(self.step_out.validate())

        return warnings

    def params(self) -> Dict:
        return {
            "block": "Pad",
            "w_in_m": self.w_in,
            "w_out_m": self.w_out,
            "w_pad_m": self.w_pad,
            "l_pad_m": self.l_pad,
            "h_m": self.h,
            "er": self.er,
        }
