"""Taper body evaluation: adaptive segmentation + lossy ABCD cascade.

The taper body is modeled as a cascade of N short lossy transmission-line
sections.  Each section has its own local Zc(f) and γ(f) computed from the
microstrip model at the section's representative width.

Segmentation uses a dual criterion:
  1. Maximum electrical length per segment at f_stop: θ_max = 5°/segmentation_tol
  2. Maximum fractional impedance change per segment: ΔZ_max = 2%/segmentation_tol

Adaptive refinement bisects segments that violate either criterion,
up to 5 passes and a hard cap of 2000 segments.
"""

from __future__ import annotations

import math
import numpy as np
from dataclasses import dataclass

from rfcore.microstrip import MicrostripModel
from rfcore.materials_ro4350b import C_0
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.network import abcd_tline, cascade, cascade_conditioned, abcd_to_s, Mat2


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

@dataclass
class TaperSegment:
    """One segment of the discretized taper body."""
    z_start: float       # start position (m)
    z_end: float         # end position (m)
    w_rep: float         # representative width (m) — at segment midpoint
    Z_rep: float         # representative impedance (Ω) — at segment midpoint

    @property
    def dz(self) -> float:
        return self.z_end - self.z_start

    @property
    def z_mid(self) -> float:
        return (self.z_start + self.z_end) / 2.0


# Segmentation constants
THETA_MAX_DEFAULT_DEG: float = 5.0    # max electrical length per segment (degrees)
DZ_FRAC_MAX_DEFAULT: float = 0.02    # max |ΔZ|/Z per segment
MAX_REFINEMENT_PASSES: int = 5
MAX_SEGMENTS: int = 2000
MIN_INITIAL_SEGMENTS: int = 50


def build_segments(
    profile: KlopfensteinProfile,
    microstrip: MicrostripModel,
    f_stop: float,
    segmentation_tol: float = 1.0,
) -> list[TaperSegment]:
    """Build adaptively refined segment list for the taper body.

    Parameters
    ----------
    profile : KlopfensteinProfile
        The impedance/width profile.
    microstrip : MicrostripModel
        Line model (for wavelength estimation).
    f_stop : float
        Upper frequency for electrical-length criterion (Hz).
    segmentation_tol : float
        Tolerance scaling.  1.0 = default thresholds.
        Higher = tighter (more segments).  Lower = coarser.

    Returns
    -------
    list of TaperSegment
    """
    L = profile.L
    if L <= 0:
        return []

    theta_max = math.radians(THETA_MAX_DEFAULT_DEG) / segmentation_tol
    dz_frac_max = DZ_FRAC_MAX_DEFAULT / segmentation_tol

    # Initial uniform grid
    # Estimate shortest wavelength at f_stop using narrowest width
    w_narrow = min(profile.w_profile)
    eeff_max = microstrip.eeff(w_narrow, f_stop)
    lambda_min = C_0 / (f_stop * math.sqrt(max(eeff_max, 1.0)))
    n_wavelength = max(1, math.ceil(L / (lambda_min / 20.0)))
    n_initial = max(MIN_INITIAL_SEGMENTS, n_wavelength)
    n_initial = min(n_initial, MAX_SEGMENTS)

    # Build initial uniform segments
    z_edges = np.linspace(0.0, L, n_initial + 1)
    segments: list[TaperSegment] = []
    for i in range(n_initial):
        z_s = z_edges[i]
        z_e = z_edges[i + 1]
        z_m = (z_s + z_e) / 2.0
        w_m = profile.w_at(z_m)
        Z_m = profile.Z_at(z_m)
        segments.append(TaperSegment(z_start=z_s, z_end=z_e, w_rep=w_m, Z_rep=Z_m))

    # Adaptive refinement
    for _pass in range(MAX_REFINEMENT_PASSES):
        if len(segments) >= MAX_SEGMENTS:
            break

        new_segments: list[TaperSegment] = []
        refined = False

        for seg in segments:
            if len(new_segments) >= MAX_SEGMENTS:
                new_segments.append(seg)
                continue

            # Check criterion 1: electrical length at f_stop
            beta_f = microstrip.beta(seg.w_rep, f_stop)
            elec_len = beta_f * seg.dz

            # Check criterion 2: fractional impedance change
            Z_start = profile.Z_at(seg.z_start)
            Z_end = profile.Z_at(seg.z_end)
            Z_mid = seg.Z_rep
            if Z_mid > 0:
                dz_frac = abs(Z_end - Z_start) / Z_mid
            else:
                dz_frac = 0.0

            needs_refine = (elec_len > theta_max) or (dz_frac > dz_frac_max)

            if needs_refine and len(new_segments) + 2 <= MAX_SEGMENTS:
                # Bisect
                z_m = seg.z_mid
                w_m1 = profile.w_at((seg.z_start + z_m) / 2.0)
                Z_m1 = profile.Z_at((seg.z_start + z_m) / 2.0)
                w_m2 = profile.w_at((z_m + seg.z_end) / 2.0)
                Z_m2 = profile.Z_at((z_m + seg.z_end) / 2.0)

                new_segments.append(TaperSegment(
                    z_start=seg.z_start, z_end=z_m, w_rep=w_m1, Z_rep=Z_m1
                ))
                new_segments.append(TaperSegment(
                    z_start=z_m, z_end=seg.z_end, w_rep=w_m2, Z_rep=Z_m2
                ))
                refined = True
            else:
                new_segments.append(seg)

        segments = new_segments
        if not refined:
            break

    return segments


# ---------------------------------------------------------------------------
# Body evaluation
# ---------------------------------------------------------------------------

@dataclass
class TaperBodyResult:
    """Result of evaluating the taper body at one frequency."""
    abcd: Mat2              # 2×2 ABCD matrix (complex)
    det_error: float        # |det(ABCD) - 1|
    n_segments: int         # number of segments used
    used_fallback: bool     # True if T-matrix fallback was needed


def evaluate_body(
    segments: list[TaperSegment],
    microstrip: MicrostripModel,
    f: float,
    z0: float = 50.0,
) -> TaperBodyResult:
    """Evaluate the taper body ABCD matrix at a single frequency.

    Each segment is a lossy transmission line section with:
      Zc_i(f) = Zc(w_rep_i, f)   [real]
      γ_i(f)  = α(w_rep_i, f) + jβ(w_rep_i, f)   [complex]
      ABCD_i  = lossy TL ABCD with γ_i·dz_i and Zc_i

    Parameters
    ----------
    segments : list of TaperSegment
    microstrip : MicrostripModel
    f : float
        Frequency (Hz).
    z0 : float
        Reference impedance for conditioning fallback.

    Returns
    -------
    TaperBodyResult
    """
    if not segments:
        identity = np.eye(2, dtype=np.complex128)
        return TaperBodyResult(abcd=identity, det_error=0.0, n_segments=0,
                               used_fallback=False)

    matrices: list[Mat2] = []
    for seg in segments:
        zc_f = microstrip.Zc(seg.w_rep, f)
        gamma_f = microstrip.gamma(seg.w_rep, f)
        gamma_l = gamma_f * seg.dz

        m = abcd_tline(zc_f, gamma_l)
        matrices.append(m)

    abcd_total, det_error = cascade_conditioned(matrices, z0)

    used_fb = det_error > 1e-3  # if we needed fallback, error was > 1e-3 initially

    return TaperBodyResult(
        abcd=abcd_total,
        det_error=det_error,
        n_segments=len(segments),
        used_fallback=used_fb,
    )


def evaluate_body_sweep(
    segments: list[TaperSegment],
    microstrip: MicrostripModel,
    freqs: np.ndarray,
    z0: float = 50.0,
) -> tuple[np.ndarray, list[float], list[bool]]:
    """Evaluate taper body S-parameters over a frequency sweep.

    Returns
    -------
    s_params : np.ndarray, shape (n_freq, 2, 2), complex
    det_errors : list of float
    fallbacks : list of bool
    """
    n_freq = len(freqs)
    s_params = np.zeros((n_freq, 2, 2), dtype=np.complex128)
    det_errors: list[float] = []
    fallbacks: list[bool] = []

    for i, f in enumerate(freqs):
        result = evaluate_body(segments, microstrip, f, z0)
        s = abcd_to_s(result.abcd, z0)
        s_params[i] = s
        det_errors.append(result.det_error)
        fallbacks.append(result.used_fallback)

    return s_params, det_errors, fallbacks
