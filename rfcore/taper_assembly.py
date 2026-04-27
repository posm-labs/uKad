"""Taper assembly — full chain construction and evaluation.

Concatenates:
  left_chain (discontinuity blocks) · taper_body · right_chain (discontinuity blocks)

Each chain is an ordered list of DiscontinuityBlock instances.
The taper body is evaluated as a cascade of lossy TL segments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_body import build_segments, evaluate_body, TaperSegment
from rfcore.network import (
    Mat2, cascade, cascade_conditioned, abcd_to_s, abcd_to_s_gen,
    abcd_identity, s_to_db,
)
from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.warnings import WarningCollector, Severity


@dataclass
class AssemblyResult:
    """Result from evaluating the full taper assembly.

    S-parameters use generalized unequal-port references:
        Port 1 referenced to z01 (= ZS, source impedance)
        Port 2 referenced to z02 (= ZL, load impedance)

    S11 represents input reflection with port 2 matched to ZL.
    S22 represents output reflection with port 1 matched to ZS.
    """
    freqs: np.ndarray                   # frequency array (Hz)
    s_params: np.ndarray                # shape (n_freq, 2, 2) complex
    s11_db: np.ndarray                  # |S11| in dB (port 1 ref = z01)
    s21_db: np.ndarray                  # |S21| in dB
    s22_db: np.ndarray                  # |S22| in dB (port 2 ref = z02)
    z01: float                          # port 1 reference impedance (ZS)
    z02: float                          # port 2 reference impedance (ZL)
    warnings: WarningCollector
    body_segments: List[TaperSegment]
    det_errors: List[float]
    used_fallbacks: List[bool]

    @property
    def is_low_confidence(self) -> bool:
        return self.warnings.is_low_confidence

    @property
    def max_s11_db(self) -> float:
        """Worst-case input return loss (most positive S11 in dB)."""
        return float(np.max(self.s11_db))

    @property
    def max_s22_db(self) -> float:
        """Worst-case output return loss (most positive S22 in dB)."""
        return float(np.max(self.s22_db))

    @property
    def max_insertion_loss_db(self) -> float:
        """Worst-case insertion loss (most negative S21 in dB)."""
        return float(np.min(self.s21_db))


class TaperAssembly:
    """Full taper chain: left discontinuities + body + right discontinuities.

    Parameters
    ----------
    settings : RFProjectSettings
    profile : KlopfensteinProfile
    microstrip : MicrostripModel
    left_chain : list of DiscontinuityBlock
        Blocks at the ZS (start) end, ordered port-1 to taper-body.
    right_chain : list of DiscontinuityBlock
        Blocks at the ZL (end) end, ordered taper-body to port-2.
    """

    def __init__(
        self,
        settings: RFProjectSettings,
        profile: KlopfensteinProfile,
        microstrip: MicrostripModel,
        left_chain: Optional[List[DiscontinuityBlock]] = None,
        right_chain: Optional[List[DiscontinuityBlock]] = None,
    ) -> None:
        self.settings = settings
        self.profile = profile
        self.microstrip = microstrip
        self.left_chain = left_chain or []
        self.right_chain = right_chain or []

        # Build segments once (they don't depend on frequency)
        self.segments = build_segments(
            profile, microstrip,
            f_stop=settings.analysis.f_stop_hz,
            segmentation_tol=settings.analysis.segmentation_tol,
        )

    def evaluate(self) -> AssemblyResult:
        """Evaluate the full chain over the configured frequency sweep."""
        analysis = self.settings.analysis
        freqs = np.linspace(
            analysis.f_start_hz, analysis.f_stop_hz, analysis.n_points
        )
        z0 = analysis.zref_ohm

        warnings = WarningCollector()

        # Collect block warnings
        for i, block in enumerate(self.left_chain):
            w = block.validate()
            warnings.add_from_strings(f"left[{i}]:{block.name}", w)

        for i, block in enumerate(self.right_chain):
            w = block.validate()
            warnings.add_from_strings(f"right[{i}]:{block.name}", w)

        # Profile warnings
        profile_warnings = self.profile.validate()
        warnings.add_from_strings("KlopfensteinProfile", profile_warnings)

        # Segment count warning
        if len(self.segments) >= 2000:
            warnings.add(
                Severity.HIGH, "Segmentation",
                f"Hit segment cap (2000). Results may lack convergence."
            )
        elif len(self.segments) >= 1000:
            warnings.add(
                Severity.WARNING, "Segmentation",
                f"High segment count ({len(self.segments)}). "
                f"Consider reducing frequency range or loosening tolerance."
            )

        # Check for low-confidence discontinuity blocks
        for block in self.left_chain + self.right_chain:
            if hasattr(block, 'is_low_confidence') and block.is_low_confidence:
                warnings.add(
                    Severity.HIGH, block.name,
                    "Block is flagged as low-confidence."
                )

        # Frequency sweep
        n_freq = len(freqs)
        s_params = np.zeros((n_freq, 2, 2), dtype=np.complex128)
        det_errors: List[float] = []
        used_fallbacks: List[bool] = []

        for fi, f in enumerate(freqs):
            # Left chain ABCD
            left_matrices = [b.abcd(f) for b in self.left_chain]
            abcd_left = cascade(left_matrices) if left_matrices else abcd_identity()

            # Body ABCD
            body_result = evaluate_body(self.segments, self.microstrip, f, z0)

            # Right chain ABCD
            right_matrices = [b.abcd(f) for b in self.right_chain]
            abcd_right = cascade(right_matrices) if right_matrices else abcd_identity()

            # Full cascade with conditioning
            all_matrices = [abcd_left, body_result.abcd, abcd_right]
            abcd_total, det_err = cascade_conditioned(all_matrices, z0)

            # Convert ABCD → S with port references matching the taper endpoints.
            # Port 1 = ZS (source side), Port 2 = ZL (load side).
            z01 = self.profile.ZS
            z02 = self.profile.ZL
            s = abcd_to_s_gen(abcd_total, z01, z02)
            s_params[fi] = s
            det_errors.append(det_err)
            used_fallbacks.append(body_result.used_fallback or det_err > 1e-3)

        # Post-process
        s11_db = np.array([s_to_db(s_params[i, 0, 0]) for i in range(n_freq)])
        s21_db = np.array([s_to_db(s_params[i, 1, 0]) for i in range(n_freq)])
        s22_db = np.array([s_to_db(s_params[i, 1, 1]) for i in range(n_freq)])

        # Check cascade conditioning across sweep
        max_det_err = max(det_errors) if det_errors else 0.0
        if max_det_err > 1e-3:
            warnings.add(
                Severity.HIGH, "ABCD Cascade",
                f"Max determinant error = {max_det_err:.2e}. "
                f"T-matrix fallback was used."
            )
        elif max_det_err > 1e-6:
            warnings.add(
                Severity.WARNING, "ABCD Cascade",
                f"Max determinant error = {max_det_err:.2e}."
            )

        return AssemblyResult(
            freqs=freqs,
            s_params=s_params,
            s11_db=s11_db,
            s21_db=s21_db,
            s22_db=s22_db,
            z01=self.profile.ZS,
            z02=self.profile.ZL,
            warnings=warnings,
            body_segments=self.segments,
            det_errors=det_errors,
            used_fallbacks=used_fallbacks,
        )
