"""Klopfenstein taper .kicad_mod footprint generator.

Generates a two-port RF footprint:
  Pad 1 (input) → Klopfenstein taper body → Pad 2 (output)

Coordinate convention (footprint-local, extends along +x):
  Pad 1 center at x = 0
  Pad 1 spans  x = [-L_land_start/2, +L_land_start/2]
  Taper body   x = [L_land_start/2, L_land_start/2 + L_body]
  Pad 2 center x = L_land_start/2 + L_body + L_land_end/2

Pad dimensions (KiCad convention):
  Pad 1: size_x = L_land_start, size_y = w_start
  Pad 2: size_x = L_land_end,   size_y = w_end

Connectivity: The fp_poly taper body overlaps into both pads by
a small amount (default 5 µm) to ensure unambiguous copper connection.

No RF core code is modified by this module.
"""

from __future__ import annotations

import os
import pathlib
import platform
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from rfcore.klopfenstein import KlopfensteinProfile


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_LANDING_M = 0.5e-3     # 0.5 mm default landing length
_PAD_OVERLAP_M = 5e-6           # 5 µm overlap into pads for connectivity
_MIN_LANDING_M = 50e-6          # 50 µm minimum landing


@dataclass
class FootprintSpec:
    """Parameters for footprint generation."""
    profile: KlopfensteinProfile
    fp_name: str = "KlopfensteinTaper"
    layer: str = "F.Cu"
    landing_start_m: float = _DEFAULT_LANDING_M
    landing_end_m: float = _DEFAULT_LANDING_M
    overlap_m: float = _PAD_OVERLAP_M

    # Metadata
    ZS: float = 50.0
    ZL: float = 75.0
    Gamma_m: float = 0.05
    f_start_hz: float = 1e9
    f_stop_hz: float = 10e9
    stackup_name: str = "RO4350B_10mil"


# ---------------------------------------------------------------------------
# Footprint generation
# ---------------------------------------------------------------------------

def generate_footprint(spec: FootprintSpec) -> str:
    """Generate .kicad_mod text for a Klopfenstein taper footprint.

    Returns
    -------
    str
        Complete .kicad_mod file content.
    """
    profile = spec.profile
    layer = spec.layer

    w_start = float(profile.w_layout[0])
    w_end = float(profile.w_layout[-1])
    L_body = float(profile.L)

    L_s = max(spec.landing_start_m, _MIN_LANDING_M)
    L_e = max(spec.landing_end_m, _MIN_LANDING_M)
    overlap = spec.overlap_m

    # ── Pad positions (mm) ──
    pad1_cx = 0.0
    pad1_sx = L_s * 1e3          # size x (mm)
    pad1_sy = w_start * 1e3      # size y (mm)

    body_start = L_s / 2         # metres from origin
    body_end = body_start + L_body

    pad2_cx = (body_end + L_e / 2) * 1e3   # mm
    pad2_sx = L_e * 1e3
    pad2_sy = w_end * 1e3

    L_total = L_s + L_body + L_e

    # ── Taper polygon (with pad overlap) ──
    z_samples = profile.z_samples
    w_layout = profile.w_layout
    n = len(z_samples)

    left_pts = []
    right_pts = []

    for i in range(n):
        z = float(z_samples[i])
        w = float(w_layout[i])
        x_mm = (body_start + z) * 1e3
        hw_mm = (w / 2) * 1e3
        # KiCad: y positive = down; use -hw for top, +hw for bottom
        left_pts.append((x_mm, -hw_mm))
        right_pts.append((x_mm, hw_mm))

    # Extend polygon into pads by overlap amount
    overlap_mm = overlap * 1e3
    # Prepend overlap into Pad 1
    x_start_overlap = (body_start - overlap) * 1e3
    hw_start = (w_start / 2) * 1e3
    left_pts.insert(0, (x_start_overlap, -hw_start))
    right_pts.insert(0, (x_start_overlap, hw_start))

    # Append overlap into Pad 2
    x_end_overlap = (body_end + overlap) * 1e3
    hw_end = (w_end / 2) * 1e3
    left_pts.append((x_end_overlap, -hw_end))
    right_pts.append((x_end_overlap, hw_end))

    # Closed polygon: left forward + right reverse
    outline = left_pts + list(reversed(right_pts))

    pts_str = "\n      ".join(
        f"(xy {x:.6f} {y:.6f})" for x, y in outline
    )

    # ── Metadata description ──
    desc = (
        f"Klopfenstein taper: "
        f"ZS={spec.ZS:.0f}Ω → ZL={spec.ZL:.0f}Ω, "
        f"Γm={spec.Gamma_m:.3f}, "
        f"f={spec.f_start_hz/1e9:.1f}–{spec.f_stop_hz/1e9:.1f}GHz, "
        f"L_body={L_body*1e3:.2f}mm, "
        f"L_total={L_total*1e3:.2f}mm, "
        f"stackup={spec.stackup_name}"
    )

    # ── Generate .kicad_mod ──
    kicad_mod = f'''(footprint "{spec.fp_name}"
  (version 20240101)
  (generator "uKad-klopfenstein")
  (generator_version "1.0")
  (layer "{layer}")
  (descr "{desc}")
  (attr smd)
  (fp_text reference "REF**" (at {pad2_cx/2:.4f} {-(max(pad1_sy, pad2_sy)/2 + 1.5):.4f}) (layer "{layer}")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_text value "{spec.fp_name}" (at {pad2_cx/2:.4f} {(max(pad1_sy, pad2_sy)/2 + 1.5):.4f}) (layer "{layer}")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_text user "${{REFERENCE}}" (at {pad2_cx/2:.4f} {-(max(pad1_sy, pad2_sy)/2 + 3.0):.4f}) (layer "F.Fab")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (pad "1" smd rect
    (at {pad1_cx:.6f} 0)
    (size {pad1_sx:.6f} {pad1_sy:.6f})
    (layers "{layer}" "F.Paste" "F.Mask")
  )
  (pad "2" smd rect
    (at {pad2_cx:.6f} 0)
    (size {pad2_sx:.6f} {pad2_sy:.6f})
    (layers "{layer}" "F.Paste" "F.Mask")
  )
  (fp_poly
    (pts
      {pts_str}
    )
    (stroke (width 0) (type solid))
    (fill solid)
    (layer "{layer}")
  )
)
'''
    return kicad_mod


def footprint_dimensions(spec: FootprintSpec) -> dict:
    """Return key dimensions of the footprint for UI display."""
    profile = spec.profile
    L_body = float(profile.L)
    w_start = float(profile.w_layout[0])
    w_end = float(profile.w_layout[-1])
    L_s = max(spec.landing_start_m, _MIN_LANDING_M)
    L_e = max(spec.landing_end_m, _MIN_LANDING_M)
    L_total = L_s + L_body + L_e

    return {
        "L_body_mm": L_body * 1e3,
        "L_landing_start_mm": L_s * 1e3,
        "L_landing_end_mm": L_e * 1e3,
        "L_total_mm": L_total * 1e3,
        "w_start_mm": w_start * 1e3,
        "w_end_mm": w_end * 1e3,
        "pad1_x_mm": 0.0,
        "pad2_x_mm": (L_s / 2 + L_body + L_e / 2) * 1e3,
    }


# ---------------------------------------------------------------------------
# Library management
# ---------------------------------------------------------------------------

def default_library_path() -> pathlib.Path:
    """Detect the best default footprint library path.

    Strategy:
    1. KICAD_USER_FOOTPRINT_DIR environment variable
    2. KiCad 8 standard user path (platform-specific)
    3. Fallback to ~/KiCad_Libraries/
    """
    # 1. Environment variable
    env_dir = os.environ.get("KICAD_USER_FOOTPRINT_DIR")
    if env_dir:
        return pathlib.Path(env_dir) / "Klopfenstein_Tapers.pretty"

    # 2. Platform-specific KiCad 8 path
    system = platform.system()
    home = pathlib.Path.home()

    if system == "Darwin":
        kicad_dir = home / "Documents" / "KiCad" / "8.0" / "3rdparty"
    elif system == "Windows":
        kicad_dir = home / "Documents" / "KiCad" / "8.0" / "3rdparty"
    else:  # Linux
        kicad_dir = home / ".local" / "share" / "kicad" / "8.0" / "3rdparty"

    if kicad_dir.exists():
        return kicad_dir / "Klopfenstein_Tapers.pretty"

    # 3. Fallback
    return home / "KiCad_Libraries" / "Klopfenstein_Tapers.pretty"


def save_footprint(
    content: str,
    fp_name: str,
    library_path: Optional[pathlib.Path] = None,
) -> pathlib.Path:
    """Save .kicad_mod footprint into a .pretty library directory.

    Parameters
    ----------
    content : str
        .kicad_mod file content (from generate_footprint).
    fp_name : str
        Footprint name (without extension).
    library_path : Path or None
        Path to the .pretty library directory.
        If None, uses default_library_path().

    Returns
    -------
    Path to the saved .kicad_mod file.
    """
    if library_path is None:
        library_path = default_library_path()

    library_path = pathlib.Path(library_path)

    # Ensure .pretty suffix
    if not library_path.name.endswith(".pretty"):
        library_path = library_path / "Klopfenstein_Tapers.pretty"

    # Create library directory
    library_path.mkdir(parents=True, exist_ok=True)

    # Save footprint
    fp_path = library_path / f"{fp_name}.kicad_mod"
    fp_path.write_text(content)

    return fp_path


def auto_footprint_name(
    ZS: float, ZL: float, Gamma_m: float, f_start_hz: float,
) -> str:
    """Generate a descriptive footprint name."""
    f_ghz = f_start_hz / 1e9
    gm_str = f"{Gamma_m:.3f}".replace(".", "p")
    return f"Klopfenstein_{ZS:.0f}_to_{ZL:.0f}_Gm{gm_str}_{f_ghz:.0f}GHz"


def library_registration_instructions(library_path: pathlib.Path) -> str:
    """Return user instructions for adding the library to KiCad."""
    return (
        f"Footprint library saved to:\n"
        f"  {library_path}\n\n"
        f"To use in KiCad:\n"
        f"  1. Open KiCad → Preferences → Manage Footprint Libraries\n"
        f"  2. Click 'Add existing library to table' (folder icon)\n"
        f"  3. Navigate to: {library_path}\n"
        f"  4. Click OK\n\n"
        f"The library will appear as 'Klopfenstein_Tapers' in the\n"
        f"footprint browser and placement dialog."
    )
