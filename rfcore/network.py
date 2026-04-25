"""Two-port network utilities: ABCD matrix construction, conversion, and cascading.

Conventions (Pozar, Microwave Engineering, 4th ed.):

    [V1]   [A  B] [V2]        I2 flows INTO port 2
    [I1] = [C  D] [I2]

    det(ABCD) = 1 for reciprocal networks.

S-parameter conversion uses real reference impedance Z0.

All functions operate on 2×2 numpy arrays (complex128).
Frequency-swept operations are done per-frequency by the caller;
these are single-frequency primitives for clarity and testability.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

# Type alias for a 2×2 complex matrix
Mat2 = np.ndarray  # shape (2, 2), dtype complex128


# ---------------------------------------------------------------------------
# ABCD matrix primitives
# ---------------------------------------------------------------------------

def abcd_tline(zc: float, gamma_l: complex) -> Mat2:
    """ABCD matrix of a lossy transmission line section.

    Parameters
    ----------
    zc : float
        Characteristic impedance (real, ohms).
    gamma_l : complex
        gamma * length  (complex: alpha*d + j*beta*d).
        gamma_l = (alpha + j*beta) * d  where d is section length in metres.

    Returns
    -------
    Mat2
        2×2 ABCD matrix (complex128).

    Notes
    -----
    ABCD = [[cosh(γd),    Zc·sinh(γd)],
            [sinh(γd)/Zc, cosh(γd)    ]]

    When γ is complex (lossy), cosh/sinh produce complex matrix elements.
    Loss enters because α > 0 makes γd have a real part.
    """
    ch = np.cosh(gamma_l)
    sh = np.sinh(gamma_l)
    return np.array([
        [ch,       zc * sh],
        [sh / zc,  ch     ],
    ], dtype=np.complex128)


def abcd_series_z(z: complex) -> Mat2:
    """ABCD matrix of a series impedance element.

    Z in series between port 1 and port 2.

    ABCD = [[1, Z],
            [0, 1]]
    """
    return np.array([
        [1.0 + 0j,  z],
        [0.0 + 0j,  1.0 + 0j],
    ], dtype=np.complex128)


def abcd_shunt_y(y: complex) -> Mat2:
    """ABCD matrix of a shunt admittance element.

    Y connected from the junction to ground.

    ABCD = [[1, 0],
            [Y, 1]]
    """
    return np.array([
        [1.0 + 0j,  0.0 + 0j],
        [y,          1.0 + 0j],
    ], dtype=np.complex128)


def abcd_shunt_z(z: complex) -> Mat2:
    """ABCD matrix of a shunt impedance element (Z to ground).

    Convenience wrapper: Y = 1/Z.
    """
    if abs(z) < 1e-30:
        # Short to ground → infinite admittance.
        # Physically means port 2 is shorted.
        return np.array([
            [1.0 + 0j, 0.0 + 0j],
            [1e30 + 0j, 1.0 + 0j],
        ], dtype=np.complex128)
    return abcd_shunt_y(1.0 / z)


def abcd_identity() -> Mat2:
    """2×2 identity ABCD matrix (through connection)."""
    return np.eye(2, dtype=np.complex128)


# ---------------------------------------------------------------------------
# Cascade
# ---------------------------------------------------------------------------

def cascade(matrices: list[Mat2]) -> Mat2:
    """Cascade (multiply) a list of ABCD matrices left to right.

    Parameters
    ----------
    matrices : list of Mat2
        Ordered list [M1, M2, ..., Mn].  M1 is closest to port 1.

    Returns
    -------
    Mat2
        Product M1 @ M2 @ ... @ Mn.
    """
    if not matrices:
        return abcd_identity()

    result = matrices[0].copy()
    for m in matrices[1:]:
        result = result @ m
    return result


def cascade_conditioned(matrices: list[Mat2], z0: float = 50.0) -> tuple[Mat2, float]:
    """Cascade with determinant conditioning check.

    Returns the cascaded ABCD and the determinant error |det - 1|.
    If the determinant error exceeds 1e-3, falls back to T-matrix cascading.

    Parameters
    ----------
    matrices : list of Mat2
        ABCD matrices to cascade.
    z0 : float
        Reference impedance for S↔ABCD conversions in fallback path.

    Returns
    -------
    (abcd_total, det_error) : (Mat2, float)
    """
    # Primary: direct ABCD multiplication
    result = cascade(matrices)
    det = result[0, 0] * result[1, 1] - result[0, 1] * result[1, 0]
    det_error = abs(det - 1.0)

    if det_error <= 1e-3:
        return result, det_error

    # Fallback: cascade via S-parameter T-matrices
    # T-matrix is better conditioned for high-loss cascades
    t_total = None  # type: Optional[Mat2]
    for m in matrices:
        s = abcd_to_s(m, z0)
        t = s_to_t(s)
        if t_total is None:
            t_total = t
        else:
            t_total = t_total @ t

    if t_total is None:
        return abcd_identity(), 0.0

    s_total = t_to_s(t_total)
    result_fb = s_to_abcd(s_total, z0)
    det_fb = result_fb[0, 0] * result_fb[1, 1] - result_fb[0, 1] * result_fb[1, 0]
    det_error_fb = abs(det_fb - 1.0)

    return result_fb, det_error_fb


# ---------------------------------------------------------------------------
# ABCD ↔ S-parameter conversion  (Pozar Eq 4.64, real Z0)
# ---------------------------------------------------------------------------

def abcd_to_s(abcd: Mat2, z0: float) -> Mat2:
    """Convert 2×2 ABCD matrix to 2×2 S-parameter matrix.

    Uses Pozar convention with real reference impedance z0.

    S11 = (A + B/Z0 - C·Z0 - D) / Δ
    S12 = 2·(AD - BC) / Δ
    S21 = 2 / Δ
    S22 = (-A + B/Z0 - C·Z0 + D) / Δ

    where Δ = A + B/Z0 + C·Z0 + D
    """
    a, b, c, d = abcd[0, 0], abcd[0, 1], abcd[1, 0], abcd[1, 1]
    delta = a + b / z0 + c * z0 + d

    s11 = (a + b / z0 - c * z0 - d) / delta
    s12 = 2.0 * (a * d - b * c) / delta
    s21 = 2.0 / delta
    s22 = (-a + b / z0 - c * z0 + d) / delta

    return np.array([[s11, s12], [s21, s22]], dtype=np.complex128)


def s_to_abcd(s: Mat2, z0: float) -> Mat2:
    """Convert 2×2 S-parameter matrix to 2×2 ABCD matrix.

    Pozar inverse:
    A = ((1+S11)(1-S22) + S12·S21) / (2·S21)
    B = Z0·((1+S11)(1+S22) - S12·S21) / (2·S21)
    C = ((1-S11)(1-S22) - S12·S21) / (2·Z0·S21)
    D = ((1-S11)(1+S22) + S12·S21) / (2·S21)
    """
    s11, s12, s21, s22 = s[0, 0], s[0, 1], s[1, 0], s[1, 1]
    denom = 2.0 * s21

    a = ((1 + s11) * (1 - s22) + s12 * s21) / denom
    b = z0 * ((1 + s11) * (1 + s22) - s12 * s21) / denom
    c = ((1 - s11) * (1 - s22) - s12 * s21) / (z0 * denom)
    d = ((1 - s11) * (1 + s22) + s12 * s21) / denom

    return np.array([[a, b], [c, d]], dtype=np.complex128)


# ---------------------------------------------------------------------------
# S ↔ T (transfer / scattering transfer matrix) for conditioned cascade
# ---------------------------------------------------------------------------

def s_to_t(s: Mat2) -> Mat2:
    """Convert S-parameters to scattering transfer (T) matrix.

    T11 = 1/S21
    T12 = -S22/S21
    T21 = S11/S21
    T22 = S12 - S11·S22/S21 = (S12·S21 - S11·S22)/S21
    """
    s11, s12, s21, s22 = s[0, 0], s[0, 1], s[1, 0], s[1, 1]
    return np.array([
        [1.0 / s21,             -s22 / s21],
        [s11 / s21, (s12 * s21 - s11 * s22) / s21],
    ], dtype=np.complex128)


def t_to_s(t: Mat2) -> Mat2:
    """Convert scattering transfer (T) matrix to S-parameters.

    S11 = T21/T11
    S12 = T22 - T21·T12/T11 = (T11·T22 - T12·T21)/T11
    S21 = 1/T11
    S22 = -T12/T11
    """
    t11, t12, t21, t22 = t[0, 0], t[0, 1], t[1, 0], t[1, 1]
    return np.array([
        [t21 / t11, (t11 * t22 - t12 * t21) / t11],
        [1.0 / t11, -t12 / t11],
    ], dtype=np.complex128)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def det_abcd(abcd: Mat2) -> complex:
    """Determinant of a 2×2 ABCD matrix."""
    return abcd[0, 0] * abcd[1, 1] - abcd[0, 1] * abcd[1, 0]


def s_to_db(s_complex: complex) -> float:
    """Convert S-parameter (complex) to magnitude in dB."""
    mag = abs(s_complex)
    if mag < 1e-30:
        return -300.0
    return 20.0 * np.log10(mag)
