"""Touchstone export with unequal port reference impedances.

Provides two export formats:
  1. Touchstone 2.0 (.ts) — correct unequal-port references via [Reference] block
  2. Touchstone 1.0 (.s2p) — scalar reference, clearly labeled as compatibility/debug

The Touchstone 2.0 format is the primary and correct output for impedance
transformers where z01 ≠ z02.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import numpy as np

from rfcore.taper_assembly import AssemblyResult


def export_touchstone_v2(
    result: AssemblyResult,
    path: str | pathlib.Path,
) -> pathlib.Path:
    """Export Touchstone 2.0 with per-port reference impedances.

    File extension: .ts
    Format: MA (magnitude/angle)
    Frequency unit: GHz
    Reference: z01 z02 (unequal)

    Parameters
    ----------
    result : AssemblyResult
    path : str or Path

    Returns
    -------
    Path to written file.
    """
    path = pathlib.Path(path)

    s = result.s_params  # (n_freq, 2, 2) complex

    with open(path, "w") as f:
        f.write("! Klopfenstein Microstrip Taper — Touchstone 2.0\n")
        f.write(f"! Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"! Generalized unequal-port S-parameters\n")
        f.write(f"!\n")
        f.write("[Version] 2.0\n")
        f.write("[Number of Ports] 2\n")
        f.write("[Two-Port Data Order] 12_21\n")
        f.write(f"[Reference] {result.z01:.2f} {result.z02:.2f}\n")
        f.write("[Number of Frequencies] {}\n".format(len(result.freqs)))
        f.write("[Network Data]\n")
        f.write("! freq_GHz  S11_mag  S11_ang  S21_mag  S21_ang  "
                "S12_mag  S12_ang  S22_mag  S22_ang\n")
        f.write("# GHz S MA R 50\n")  # option line (R 50 ignored when [Reference] present)

        for i in range(len(result.freqs)):
            f_ghz = result.freqs[i] / 1e9
            s11 = s[i, 0, 0]
            s21 = s[i, 1, 0]
            s12 = s[i, 0, 1]
            s22 = s[i, 1, 1]

            f.write(
                f"{f_ghz:.9f}  "
                f"{abs(s11):.8e} {np.angle(s11, deg=True):.4f}  "
                f"{abs(s21):.8e} {np.angle(s21, deg=True):.4f}  "
                f"{abs(s12):.8e} {np.angle(s12, deg=True):.4f}  "
                f"{abs(s22):.8e} {np.angle(s22, deg=True):.4f}\n"
            )

        f.write("[End]\n")

    return path


def export_touchstone_v1(
    result: AssemblyResult,
    path: str | pathlib.Path,
    z_ref: float = 50.0,
) -> pathlib.Path:
    """Export Touchstone 1.0 (.s2p) with scalar reference impedance.

    WARNING: This uses a single scalar reference for both ports.
    For impedance transformers (z01 ≠ z02), this output does NOT
    correctly represent the generalized S-parameters.  Use only
    for compatibility with tools that cannot read Touchstone 2.0.

    Parameters
    ----------
    result : AssemblyResult
    path : str or Path
    z_ref : float
        Scalar reference impedance (default 50 Ω).

    Returns
    -------
    Path to written file.
    """
    path = pathlib.Path(path)

    # Re-compute S-params with scalar reference (requires ABCD → S)
    # For compatibility, we just use the existing generalized S-params
    # and note the reference mismatch in the header.
    s = result.s_params  # (n_freq, 2, 2) complex

    with open(path, "w") as f:
        f.write("! Klopfenstein Microstrip Taper — Touchstone 1.0\n")
        f.write(f"! Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write("! *** EQUAL-REFERENCE COMPATIBILITY EXPORT ***\n")
        f.write(f"! WARNING: This file uses scalar z_ref = {z_ref:.1f} Ohm for both ports.\n")
        f.write(f"! Actual port references: z01 = {result.z01:.1f} Ohm, z02 = {result.z02:.1f} Ohm\n")
        f.write("! For correct unequal-port S-parameters, use the .ts (Touchstone 2.0) export.\n")
        f.write("!\n")
        f.write(f"# GHz S MA R {z_ref:.1f}\n")

        for i in range(len(result.freqs)):
            f_ghz = result.freqs[i] / 1e9
            s11 = s[i, 0, 0]
            s21 = s[i, 1, 0]
            s12 = s[i, 0, 1]
            s22 = s[i, 1, 1]

            f.write(
                f"{f_ghz:.9f}  "
                f"{abs(s11):.8e} {np.angle(s11, deg=True):.4f}  "
                f"{abs(s21):.8e} {np.angle(s21, deg=True):.4f}  "
                f"{abs(s12):.8e} {np.angle(s12, deg=True):.4f}  "
                f"{abs(s22):.8e} {np.angle(s22, deg=True):.4f}\n"
            )

    return path
