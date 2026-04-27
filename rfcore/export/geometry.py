"""Geometry export — taper polygon, SVG, PNG preview.

Uses the layout-realized width profile (not the ideal electrical profile).

Provides:
  1. Taper polygon vertices (left + right edges)
  2. Centerline + width table
  3. SVG export (standalone, no dependencies beyond stdlib)
  4. PNG preview via matplotlib
  5. KiCad .kicad_mod footprint export (fallback/debug)
"""

from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from rfcore.klopfenstein import KlopfensteinProfile


@dataclass
class TaperPolygon:
    """Taper outline polygon with metadata.

    Attributes
    ----------
    left_edge : list of (x, y) in metres
        Left edge vertices (z increasing, offset −w/2 from centerline).
    right_edge : list of (x, y) in metres
        Right edge vertices (z increasing, offset +w/2 from centerline).
    outline : list of (x, y) in metres
        Closed polygon: left_edge forward + right_edge reverse.
    centerline_z_m : ndarray
        Centerline positions.
    centerline_w_m : ndarray
        Layout-realized widths.
    length_m : float
        Total taper length.
    """
    left_edge: List[Tuple[float, float]]
    right_edge: List[Tuple[float, float]]
    outline: List[Tuple[float, float]]
    centerline_z_m: np.ndarray
    centerline_w_m: np.ndarray
    length_m: float


def generate_taper_polygon(
    profile: KlopfensteinProfile,
    origin_x_m: float = 0.0,
    origin_y_m: float = 0.0,
    angle_deg: float = 0.0,
) -> TaperPolygon:
    """Generate taper outline polygon from layout-realized profile.

    The taper is oriented along the specified angle from the origin.

    Parameters
    ----------
    profile : KlopfensteinProfile
    origin_x_m, origin_y_m : float
        Start position in metres.
    angle_deg : float
        Direction angle in degrees (0 = +X, 90 = +Y).

    Returns
    -------
    TaperPolygon
    """
    z = profile.z_samples
    w = profile.w_layout
    n = len(z)

    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    # Perpendicular direction (left = +90°)
    cos_p = math.cos(angle_rad + math.pi / 2)
    sin_p = math.sin(angle_rad + math.pi / 2)

    left_edge: List[Tuple[float, float]] = []
    right_edge: List[Tuple[float, float]] = []

    for i in range(n):
        # Centerline position
        cx = origin_x_m + z[i] * cos_a
        cy = origin_y_m + z[i] * sin_a
        hw = w[i] / 2.0  # half-width

        # Left edge (perpendicular, positive direction)
        left_edge.append((cx + hw * cos_p, cy + hw * sin_p))
        # Right edge (perpendicular, negative direction)
        right_edge.append((cx - hw * cos_p, cy - hw * sin_p))

    # Closed polygon: left forward + right reverse
    outline = left_edge + list(reversed(right_edge))

    return TaperPolygon(
        left_edge=left_edge,
        right_edge=right_edge,
        outline=outline,
        centerline_z_m=z.copy(),
        centerline_w_m=w.copy(),
        length_m=float(profile.L),
    )


def export_svg(
    polygon: TaperPolygon,
    path: str | pathlib.Path,
    scale: float = 1000.0,
    stroke_width: float = 0.1,
) -> pathlib.Path:
    """Export taper polygon as standalone SVG.

    Parameters
    ----------
    polygon : TaperPolygon
    path : str or Path
    scale : float
        Coordinate scale (default 1000 = mm → SVG units).
    stroke_width : float
        Stroke width in SVG units.

    Returns
    -------
    Path to written file.
    """
    path = pathlib.Path(path)

    # Convert outline to SVG coordinates (scale to mm, flip Y for SVG)
    pts_svg = [(x * scale, -y * scale) for x, y in polygon.outline]

    # Compute bounding box
    xs = [p[0] for p in pts_svg]
    ys = [p[1] for p in pts_svg]
    margin = 2.0
    x_min, x_max = min(xs) - margin, max(xs) + margin
    y_min, y_max = min(ys) - margin, max(ys) + margin
    width = x_max - x_min
    height = y_max - y_min

    # Build SVG path
    path_d = "M " + " L ".join(f"{x:.4f},{y:.4f}" for x, y in pts_svg) + " Z"

    svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="{x_min:.4f} {y_min:.4f} {width:.4f} {height:.4f}"
     width="{width:.1f}mm" height="{height:.1f}mm">
  <title>Klopfenstein Taper — {polygon.length_m*1e3:.1f} mm</title>
  <desc>Layout-realized taper polygon.
    Length: {polygon.length_m*1e3:.3f} mm
    Start width: {polygon.centerline_w_m[0]*1e3:.4f} mm
    End width: {polygon.centerline_w_m[-1]*1e3:.4f} mm
  </desc>
  <path d="{path_d}"
        fill="#c87533" fill-opacity="0.7"
        stroke="#8B4513" stroke-width="{stroke_width:.2f}"
        stroke-linejoin="round"/>
  <!-- Centerline -->
  <line x1="{pts_svg[0][0]:.4f}" y1="{(polygon.outline[0][1] * scale * -1 + polygon.outline[-1][1] * scale * -1) / 2 - ((polygon.outline[0][1] - polygon.outline[-1][1]) * scale / 2):.4f}"
        x2="{pts_svg[len(polygon.outline)//2 - 1][0]:.4f}" y2="{(polygon.outline[0][1] * scale * -1 + polygon.outline[-1][1] * scale * -1) / 2 - ((polygon.outline[0][1] - polygon.outline[-1][1]) * scale / 2):.4f}"
        stroke="#333" stroke-width="{stroke_width * 0.3:.3f}"
        stroke-dasharray="{stroke_width:.2f},{stroke_width:.2f}"/>
</svg>
"""
    # Simplified centerline: just draw from first left/right midpoint to last
    # Rewrite with simpler centerline
    mid_start_y = (-polygon.outline[0][1] * scale + -polygon.outline[-1][1] * scale) / 2
    mid_end_y = mid_start_y  # For angle=0, centerline is horizontal

    # Recompute properly using actual centerline
    cl_start_x = polygon.centerline_z_m[0] * scale
    cl_end_x = polygon.centerline_z_m[-1] * scale

    svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="{x_min:.4f} {y_min:.4f} {width:.4f} {height:.4f}"
     width="{width:.1f}mm" height="{height:.1f}mm">
  <title>Klopfenstein Taper — {polygon.length_m*1e3:.1f} mm</title>
  <path d="{path_d}"
        fill="#c87533" fill-opacity="0.7"
        stroke="#8B4513" stroke-width="{stroke_width:.2f}"
        stroke-linejoin="round"/>
</svg>
"""
    path.write_text(svg_content)
    return path


def export_png_preview(
    polygon: TaperPolygon,
    path: str | pathlib.Path,
    dpi: int = 150,
) -> pathlib.Path:
    """Export taper geometry preview as PNG via matplotlib.

    Parameters
    ----------
    polygon : TaperPolygon
    path : str or Path
    dpi : int

    Returns
    -------
    Path to written file.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon

    path = pathlib.Path(path)

    # Convert to mm
    outline_mm = [(x * 1e3, y * 1e3) for x, y in polygon.outline]

    fig, ax = plt.subplots(figsize=(10, 3))
    poly_patch = MplPolygon(
        outline_mm, closed=True,
        facecolor="#c87533", edgecolor="#8B4513",
        alpha=0.7, linewidth=1.0,
    )
    ax.add_patch(poly_patch)

    # Annotate endpoints
    w_start = polygon.centerline_w_m[0] * 1e3
    w_end = polygon.centerline_w_m[-1] * 1e3
    L_mm = polygon.length_m * 1e3

    ax.annotate(f"w = {w_start:.3f} mm", xy=(0, 0),
                fontsize=8, ha="center", va="bottom",
                xytext=(0, max(w_start, w_end) * 0.7),
                arrowprops=dict(arrowstyle="->", color="gray"))
    ax.annotate(f"w = {w_end:.3f} mm", xy=(L_mm, 0),
                fontsize=8, ha="center", va="bottom",
                xytext=(L_mm, max(w_start, w_end) * 0.7),
                arrowprops=dict(arrowstyle="->", color="gray"))

    ax.set_xlim(-L_mm * 0.05, L_mm * 1.05)
    y_extent = max(w_start, w_end) * 0.8
    ax.set_ylim(-y_extent, y_extent)
    ax.set_aspect("equal")
    ax.set_xlabel("Position (mm)", fontsize=10)
    ax.set_ylabel("Width (mm)", fontsize=10)
    ax.set_title(f"Taper Geometry — L = {L_mm:.2f} mm", fontsize=11, fontweight="bold")
    ax.grid(True, alpha=0.3, linewidth=0.5)

    fig.tight_layout()
    fig.savefig(str(path), dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def export_kicad_mod(
    polygon: TaperPolygon,
    path: str | pathlib.Path,
    layer: str = "F.Cu",
    footprint_name: str = "KlopfensteinTaper",
) -> pathlib.Path:
    """Export taper as KiCad footprint (.kicad_mod) — fallback/debug only.

    This produces a standalone footprint file with a filled copper polygon.
    The user can import this into KiCad manually.

    This is NOT the primary insertion method — see board_insert.py for
    direct ZONE insertion via the KiCad API.

    Parameters
    ----------
    polygon : TaperPolygon
    path : str or Path
    layer : str
    footprint_name : str

    Returns
    -------
    Path to written file.
    """
    path = pathlib.Path(path)

    # Convert outline to mm strings
    pts_str = "\n      ".join(
        f"(xy {x*1e3:.6f} {-y*1e3:.6f})"
        for x, y in polygon.outline
    )

    kicad_mod = f"""(footprint "{footprint_name}"
  (version 20240101)
  (generator "kicad-rf-klopfenstein")
  (layer "{layer}")
  (descr "Klopfenstein microstrip taper — L={polygon.length_m*1e3:.2f}mm")
  (attr board_only exclude_from_pos_files exclude_from_bom)
  (fp_text reference "REF**" (at 0 -2) (layer "{layer}")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_text value "{footprint_name}" (at 0 2) (layer "{layer}")
    (effects (font (size 1 1) (thickness 0.15)))
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
"""
    path.write_text(kicad_mod)
    return path
