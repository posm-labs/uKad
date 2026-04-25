"""Rogers RO4350B laminate material constants and validation.

Source: Rogers Corporation RO4350B datasheet (rev 2024).
All values stored in SI units.

Design note on Dk:
  Rogers publishes Dk = 3.48 ± 0.05 at 10 GHz (process Dk, IPC TM-650 2.5.5.5,
  clamped stripline resonator method).
  Rogers also publishes a "Design Dk" of 3.66 which accounts for the effect of
  copper foil roughness on the effective Dk seen by microstrip circuits.
  This tool defaults to the process Dk = 3.48 as specified in the project spec.
  Users are warned in the UI that the design Dk (3.66) may give better agreement
  with fabricated boards, especially for wide microstrip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Physical constants (SI)
# ---------------------------------------------------------------------------

MU_0: float = 1.2566370614359173e-6   # H/m  (4π × 10⁻⁷)
EPS_0: float = 8.854187817620389e-12  # F/m
C_0: float = 299_792_458.0            # m/s  (speed of light in vacuum)
ETA_0: float = 376.73031346177066     # Ω    (impedance of free space, 120π)


# ---------------------------------------------------------------------------
# RO4350B material presets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RO4350BPreset:
    """Validated material preset for Rogers RO4350B.

    Attributes use SI units throughout.
    """

    # Dielectric
    dk_process_10ghz: float = 3.48            # ±0.05
    dk_design: float = 3.66                   # includes roughness effect
    df_10ghz: float = 0.0037                  # loss tangent at 10 GHz

    # Standard substrate thicknesses (m) — most common options
    thickness_4mil_m: float = 0.1016e-3       # 0.004"
    thickness_6p6mil_m: float = 0.1676e-3     # 0.0066"
    thickness_10mil_m: float = 0.254e-3       # 0.010"
    thickness_13mil_m: float = 0.3302e-3      # 0.013"
    thickness_16p6mil_m: float = 0.4216e-3    # 0.0166"
    thickness_20mil_m: float = 0.508e-3       # 0.020"
    thickness_30mil_m: float = 0.762e-3       # 0.030"
    thickness_60mil_m: float = 1.524e-3       # 0.060"

    # Copper (annealed copper reference)
    cu_conductivity_s_per_m: float = 5.8e7
    cu_1oz_thickness_m: float = 35.0e-6       # 1 oz/ft² ≈ 35 μm
    cu_0p5oz_thickness_m: float = 17.5e-6     # 0.5 oz/ft² ≈ 17.5 μm
    cu_2oz_thickness_m: float = 70.0e-6       # 2 oz/ft² ≈ 70 μm

    # Surface roughness (typical rolled/ED copper on RO4350B)
    roughness_rolled_m: float = 0.3e-6        # RMS ≈ 0.3 μm
    roughness_ed_standard_m: float = 1.5e-6   # RMS ≈ 1.5 μm (standard ED)
    roughness_ed_rtf_m: float = 0.5e-6        # RMS ≈ 0.5 μm (reverse-treated foil)

    # Thermal
    tg_c: float = 280.0                       # glass transition temperature (°C)
    cte_z_ppm_per_c: float = 46.0             # Z-axis CTE (ppm/°C)

    @property
    def standard_thicknesses_m(self) -> list[float]:
        """All standard substrate thicknesses in metres."""
        return [
            self.thickness_4mil_m,
            self.thickness_6p6mil_m,
            self.thickness_10mil_m,
            self.thickness_13mil_m,
            self.thickness_16p6mil_m,
            self.thickness_20mil_m,
            self.thickness_30mil_m,
            self.thickness_60mil_m,
        ]


# Module-level singleton
RO4350B = RO4350BPreset()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_ro4350b_stackup(
    substrate_height_m: float,
    dk_design: float,
    df_10ghz: float,
    copper_thickness_m: float,
    conductivity_s_per_m: float,
    surface_roughness_m: float = 0.0,
) -> list[str]:
    """Validate user-supplied stackup parameters against RO4350B ranges.

    Returns a list of warning/error strings.  Empty list means all OK.
    Warnings are prefixed with 'WARNING:' and errors with 'ERROR:'.
    """
    msgs: list[str] = []

    # Dk range check
    if not (3.0 <= dk_design <= 4.2):
        msgs.append(
            f"ERROR: dk_design={dk_design:.3f} is outside plausible RO4350B range "
            f"[3.0, 4.2].  Process Dk=3.48, Design Dk=3.66."
        )
    elif dk_design < 3.43 or dk_design > 3.53:
        if abs(dk_design - 3.66) > 0.1:
            msgs.append(
                f"WARNING: dk_design={dk_design:.3f} is outside the typical process "
                f"Dk range (3.43–3.53) and not near the design Dk (3.66).  "
                f"Verify this is intentional."
            )

    # Df range check
    if not (0.001 <= df_10ghz <= 0.01):
        msgs.append(
            f"WARNING: df_10ghz={df_10ghz:.4f} is outside typical RO4350B range "
            f"[0.001, 0.01].  Nominal = 0.0037."
        )

    # Substrate thickness — check against standard list
    standard = RO4350B.standard_thicknesses_m
    closest = min(standard, key=lambda t: abs(t - substrate_height_m))
    if abs(substrate_height_m - closest) / closest > 0.05:
        msgs.append(
            f"WARNING: substrate_height_m={substrate_height_m*1e6:.1f} μm does not "
            f"match any standard RO4350B thickness.  Nearest standard: "
            f"{closest*1e6:.1f} μm."
        )

    # Copper thickness
    if copper_thickness_m < 5e-6 or copper_thickness_m > 150e-6:
        msgs.append(
            f"WARNING: copper_thickness_m={copper_thickness_m*1e6:.1f} μm is outside "
            f"typical PCB copper range [5, 150] μm."
        )

    # Conductivity
    if conductivity_s_per_m < 1e6 or conductivity_s_per_m > 7e7:
        msgs.append(
            f"WARNING: conductivity={conductivity_s_per_m:.2e} S/m is outside "
            f"typical conductor range.  Annealed Cu = 5.8e7 S/m."
        )

    # Surface roughness
    if surface_roughness_m > 5e-6:
        msgs.append(
            f"WARNING: surface_roughness_m={surface_roughness_m*1e6:.2f} μm is very "
            f"high.  Typical RO4350B roughness: 0.3–1.5 μm RMS."
        )

    return msgs
