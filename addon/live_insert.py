"""Live insertion — transform RF taper profile into board coordinates.

This is the bridge between the RF engine (which works in local z-space)
and the KiCad board (which needs global x,y board coordinates).

Key responsibilities:
  1. Anchor polygon at the selected start endpoint
  2. Orient toward the selected end endpoint
  3. Use RF-synthesized length (not gap length) by default
  4. Detect gap mismatch and warn
  5. Add connection overlap where geometry is compatible
  6. Log debug info for coordinate verification
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.export.geometry import TaperPolygon
from addon.selection import SelectionResult

logger = logging.getLogger(__name__)

# Default overlap for physical connectivity (metres)
DEFAULT_OVERLAP_M = 25e-6  # 25 µm

# Gap length tolerance for "approximately equal"
GAP_TOLERANCE_RATIO = 0.02  # 2%


@dataclass
class InsertionPlan:
    """Complete plan for inserting a taper into a KiCad board.

    Contains the polygon in board coordinates plus all metadata
    and warnings needed for the dialog/report.
    """
    polygon: TaperPolygon

    # Geometry context
    start_xy_m: Tuple[float, float]       # anchor point (board coords)
    end_xy_m: Tuple[float, float]         # selected output endpoint
    predicted_end_xy_m: Tuple[float, float]  # where taper actually ends
    tangent: Tuple[float, float]          # unit tangent vector
    normal: Tuple[float, float]           # unit normal vector

    # Lengths
    L_gap_m: float          # distance between selected endpoints
    L_min_m: float          # minimum RF synthesis length
    L_actual_m: float       # actual taper length used
    length_margin: float

    # Widths
    w_start_m: float        # layout width at start
    w_end_m: float          # layout width at end
    w_track_start_m: float  # selected track width at start
    w_track_end_m: float    # selected track width at end

    # Connectivity
    connects_start: bool = True
    connects_end: bool = False
    overlap_m: float = DEFAULT_OVERLAP_M

    # Layer / net
    layer: str = "F.Cu"
    net_name: str = ""

    # Warnings
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    @property
    def gap_matches(self) -> bool:
        """True if gap length approximately equals taper length."""
        if self.L_gap_m <= 0:
            return False
        ratio = abs(self.L_actual_m - self.L_gap_m) / self.L_gap_m
        return ratio < GAP_TOLERANCE_RATIO

    def debug_summary(self) -> str:
        """Human-readable debug string for logging before insertion."""
        lines = [
            "=== INSERTION DEBUG ===",
            f"  Start point:     ({self.start_xy_m[0]*1e3:.3f}, {self.start_xy_m[1]*1e3:.3f}) mm",
            f"  Selected end:    ({self.end_xy_m[0]*1e3:.3f}, {self.end_xy_m[1]*1e3:.3f}) mm",
            f"  Predicted end:   ({self.predicted_end_xy_m[0]*1e3:.3f}, {self.predicted_end_xy_m[1]*1e3:.3f}) mm",
            f"  L_gap:           {self.L_gap_m*1e3:.3f} mm",
            f"  L_min:           {self.L_min_m*1e3:.3f} mm",
            f"  L_actual:        {self.L_actual_m*1e3:.3f} mm",
            f"  Length margin:   {self.length_margin:.2f}",
            f"  Gap matches:     {self.gap_matches}",
            f"  Connects start:  {self.connects_start}",
            f"  Connects end:    {self.connects_end}",
            f"  w_start:         {self.w_start_m*1e3:.4f} mm (track: {self.w_track_start_m*1e3:.4f} mm)",
            f"  w_end:           {self.w_end_m*1e3:.4f} mm (track: {self.w_track_end_m*1e3:.4f} mm)",
            f"  Layer:           {self.layer}",
            f"  Net:             {self.net_name}",
            f"  Overlap:         {self.overlap_m*1e6:.0f} µm",
            f"  Polygon verts:   {len(self.polygon.outline)}",
        ]
        # Bounding box
        xs = [p[0] for p in self.polygon.outline]
        ys = [p[1] for p in self.polygon.outline]
        lines.append(f"  BBox X:          [{min(xs)*1e3:.3f}, {max(xs)*1e3:.3f}] mm")
        lines.append(f"  BBox Y:          [{min(ys)*1e3:.3f}, {max(ys)*1e3:.3f}] mm")
        p0 = self.polygon.outline[0]
        pN = self.polygon.outline[len(self.polygon.outline)//2 - 1]
        lines.append(f"  First vertex:    ({p0[0]*1e3:.3f}, {p0[1]*1e3:.3f}) mm")
        lines.append(f"  Mid vertex:      ({pN[0]*1e3:.3f}, {pN[1]*1e3:.3f}) mm")

        if self.warnings:
            lines.append("  WARNINGS:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        lines.append("=== END DEBUG ===")
        return "\n".join(lines)


def prepare_insertion(
    profile: KlopfensteinProfile,
    selection: SelectionResult,
    overlap_m: float = DEFAULT_OVERLAP_M,
) -> InsertionPlan:
    """Prepare a taper polygon in board coordinates for insertion.

    The taper is:
      - Anchored at the selected start endpoint
      - Oriented toward the selected end endpoint
      - Uses the RF-synthesized length (profile.L), NOT the gap length
      - Warns if the gap doesn't match the taper length

    Parameters
    ----------
    profile : KlopfensteinProfile
        Synthesized taper profile with layout-realized widths.
    selection : SelectionResult
        Track selection with endpoints in metres.
    overlap_m : float
        Connection overlap in metres.

    Returns
    -------
    InsertionPlan
        Polygon in board coordinates plus metadata and warnings.
    """
    warnings: List[str] = []
    info: List[str] = []

    # ── Endpoints ──
    sx, sy = selection.start_x_m, selection.start_y_m
    ex, ey = selection.end_x_m, selection.end_y_m

    # ── Direction vector ──
    dx = ex - sx
    dy = ey - sy
    L_gap = math.sqrt(dx * dx + dy * dy)

    if L_gap < 1e-9:
        # Degenerate: use selection tangent as direction, gap = 0
        angle_rad = math.radians(selection.start_tangent_deg)
        tx, ty = math.cos(angle_rad), math.sin(angle_rad)
        L_gap = 0.0
        warnings.append("Selected endpoints are coincident. Using tangent direction.")
    else:
        tx, ty = dx / L_gap, dy / L_gap

    # Normal (perpendicular, 90° CCW)
    nx, ny = -ty, tx

    # ── RF synthesized length ──
    L_actual = float(profile.L)
    L_min = L_actual / profile.length_margin if profile.length_margin > 0 else L_actual

    # ── Gap mismatch detection ──
    connects_end = False
    if L_gap > 0:
        ratio = abs(L_actual - L_gap) / L_gap
        if ratio < GAP_TOLERANCE_RATIO:
            connects_end = True
            info.append(
                f"Gap ({L_gap*1e3:.2f} mm) matches taper length "
                f"({L_actual*1e3:.2f} mm). Both endpoints will connect."
            )
        elif L_actual > L_gap:
            warnings.append(
                f"Taper length ({L_actual*1e3:.2f} mm) exceeds selected gap "
                f"({L_gap*1e3:.2f} mm) by {(L_actual-L_gap)*1e3:.2f} mm. "
                f"The taper will extend past the output endpoint. "
                f"Move/trim the output trace after insertion, or reduce length_margin."
            )
        else:
            warnings.append(
                f"Selected gap ({L_gap*1e3:.2f} mm) is longer than taper "
                f"({L_actual*1e3:.2f} mm) by {(L_gap-L_actual)*1e3:.2f} mm. "
                f"The taper will end before the output endpoint. "
                f"Add/move trace to connect, or increase length_margin."
            )

    # ── Width checks ──
    w_start = float(profile.w_layout[0])
    w_end = float(profile.w_layout[-1])
    w_track_start = selection.start_width_m
    w_track_end = selection.end_width_m

    if w_track_start > 0 and abs(w_start - w_track_start) / max(w_track_start, 1e-9) > 0.05:
        warnings.append(
            f"Taper start width ({w_start*1e3:.4f} mm) differs from selected "
            f"track width ({w_track_start*1e3:.4f} mm) by "
            f"{abs(w_start-w_track_start)*1e3:.4f} mm."
        )
    if w_track_end > 0 and abs(w_end - w_track_end) / max(w_track_end, 1e-9) > 0.05:
        warnings.append(
            f"Taper end width ({w_end*1e3:.4f} mm) differs from selected "
            f"track width ({w_track_end*1e3:.4f} mm) by "
            f"{abs(w_end-w_track_end)*1e3:.4f} mm."
        )

    # ── Generate polygon in board coordinates ──
    z = profile.z_samples       # local position along taper (0..L)
    w = profile.w_layout        # layout-realized width at each position
    n = len(z)

    left_edge: List[Tuple[float, float]] = []
    right_edge: List[Tuple[float, float]] = []

    # Start overlap: extend backward
    if overlap_m > 0:
        cx = sx - overlap_m * tx
        cy = sy - overlap_m * ty
        hw = float(w[0]) / 2.0
        left_edge.append((cx + hw * nx, cy + hw * ny))
        right_edge.append((cx - hw * nx, cy - hw * ny))

    # Main taper body
    for i in range(n):
        s = float(z[i])
        cx = sx + s * tx
        cy = sy + s * ty
        hw = float(w[i]) / 2.0
        left_edge.append((cx + hw * nx, cy + hw * ny))
        right_edge.append((cx - hw * nx, cy - hw * ny))

    # End overlap: extend forward (only if connecting end)
    if overlap_m > 0 and connects_end:
        cx = sx + L_actual * tx + overlap_m * tx
        cy = sy + L_actual * ty + overlap_m * ty
        hw = float(w[-1]) / 2.0
        left_edge.append((cx + hw * nx, cy + hw * ny))
        right_edge.append((cx - hw * nx, cy - hw * ny))

    # Closed polygon: left forward + right reverse
    outline = left_edge + list(reversed(right_edge))

    # Predicted taper end in board coords
    pred_end_x = sx + L_actual * tx
    pred_end_y = sy + L_actual * ty

    polygon = TaperPolygon(
        left_edge=left_edge,
        right_edge=right_edge,
        outline=outline,
        centerline_z_m=z.copy(),
        centerline_w_m=w.copy(),
        length_m=L_actual,
    )

    plan = InsertionPlan(
        polygon=polygon,
        start_xy_m=(sx, sy),
        end_xy_m=(ex, ey),
        predicted_end_xy_m=(pred_end_x, pred_end_y),
        tangent=(tx, ty),
        normal=(nx, ny),
        L_gap_m=L_gap,
        L_min_m=L_min,
        L_actual_m=L_actual,
        length_margin=profile.length_margin,
        w_start_m=w_start,
        w_end_m=w_end,
        w_track_start_m=w_track_start,
        w_track_end_m=w_track_end,
        connects_start=True,
        connects_end=connects_end,
        overlap_m=overlap_m,
        layer=selection.layer,
        net_name=selection.net_name,
        warnings=warnings,
        info=info,
    )

    logger.info(plan.debug_summary())
    return plan
