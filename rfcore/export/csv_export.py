"""CSV export for frequency-domain S-parameters and taper geometry.

Exports two CSV files:
  1. Frequency-domain S-parameter data with port reference metadata
  2. Geometry profile (z, w, Z) using layout-realized widths
"""

from __future__ import annotations

import pathlib
from typing import Optional

import numpy as np

from rfcore.taper_assembly import AssemblyResult
from rfcore.klopfenstein import KlopfensteinProfile


def export_frequency_csv(
    result: AssemblyResult,
    path: str | pathlib.Path,
) -> pathlib.Path:
    """Export frequency-domain S-parameter data to CSV.

    Header comment lines document the port reference impedances.
    Columns: f_hz, s11_db, s11_phase_deg, s21_db, s21_phase_deg,
             s22_db, s22_phase_deg

    Parameters
    ----------
    result : AssemblyResult
    path : str or Path

    Returns
    -------
    Path to written file.
    """
    path = pathlib.Path(path)

    s11 = result.s_params[:, 0, 0]
    s21 = result.s_params[:, 1, 0]
    s22 = result.s_params[:, 1, 1]

    s11_phase = np.angle(s11, deg=True)
    s21_phase = np.angle(s21, deg=True)
    s22_phase = np.angle(s22, deg=True)

    with open(path, "w") as f:
        f.write(f"# Klopfenstein Taper — Frequency-Domain S-Parameters\n")
        f.write(f"# Port 1 reference: z01 = {result.z01:.2f} Ohm (ZS)\n")
        f.write(f"# Port 2 reference: z02 = {result.z02:.2f} Ohm (ZL)\n")
        f.write(f"# Generalized unequal-port S-parameters\n")
        f.write(f"# Max |S11| = {result.max_s11_db:.2f} dB\n")
        f.write(f"# Max |S22| = {result.max_s22_db:.2f} dB\n")
        f.write(f"# Worst IL  = {result.max_insertion_loss_db:.2f} dB\n")
        f.write(f"#\n")
        f.write("f_hz,s11_db,s11_phase_deg,s21_db,s21_phase_deg,"
                "s22_db,s22_phase_deg\n")

        for i in range(len(result.freqs)):
            f.write(
                f"{result.freqs[i]:.1f},"
                f"{result.s11_db[i]:.4f},{s11_phase[i]:.2f},"
                f"{result.s21_db[i]:.4f},{s21_phase[i]:.2f},"
                f"{result.s22_db[i]:.4f},{s22_phase[i]:.2f}\n"
            )

    return path


def export_geometry_csv(
    profile: KlopfensteinProfile,
    path: str | pathlib.Path,
) -> pathlib.Path:
    """Export taper geometry profile to CSV.

    Uses the layout-realized width profile (endpoints clamped to feed widths).
    Columns: z_m, z_mm, w_m, w_mm, Z_ohm

    Parameters
    ----------
    profile : KlopfensteinProfile
    path : str or Path

    Returns
    -------
    Path to written file.
    """
    path = pathlib.Path(path)

    z = profile.z_samples
    w = profile.w_layout
    Z = profile.Z_profile

    with open(path, "w") as f:
        f.write(f"# Klopfenstein Taper — Geometry Profile\n")
        f.write(f"# ZS = {profile.ZS:.2f} Ohm, ZL = {profile.ZL:.2f} Ohm\n")
        f.write(f"# Gamma_m = {profile.Gamma_m:.6f}\n")
        f.write(f"# L = {profile.L*1e3:.3f} mm\n")
        f.write(f"# Layout-realized width profile (endpoints clamped)\n")
        f.write(f"#\n")
        f.write("z_m,z_mm,w_m,w_mm,Z_ohm\n")

        for i in range(len(z)):
            f.write(
                f"{z[i]:.9e},{z[i]*1e3:.6f},"
                f"{w[i]:.9e},{w[i]*1e3:.6f},"
                f"{Z[i]:.4f}\n"
            )

    return path
