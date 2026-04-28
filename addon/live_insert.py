"""One-trace Klopfenstein launch — composite polygon in board coordinates.

v1 workflow: select one input trace → synthesize → generate composite overlay.

The composite polygon has three sections:

  [input overlap]  [RF Klopfenstein body]  [output landing]
  ←── L_overlap ──→←──── L_body ────────→←── L_landing ──→
      w = w_start      Klopfenstein          w = w_end
                       taper profile

- Input overlap:  same width as selected track, extends backward
                  over the track's free end to bury the rounded cap.
- RF body:        Klopfenstein profile, length = profile.L.
- Output landing: same width as synthesized output, extends forward.
                  User routes the next trace from here.

No track trimming.  No output trace required.  Non-destructive overlay.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.export.geometry import TaperPolygon
from addon.selection import SelectionResult

logger = logging.getLogger(__name__)


@dataclass
class InsertionPlan:
    """Complete plan for inserting a one-trace Klopfenstein launch."""

    polygon: TaperPolygon

    # Launch geometry
    launch_xy_m: Tuple[float, float]          # selected track free endpoint
    predicted_end_xy_m: Tuple[float, float]    # where output landing ends
    tangent: Tuple[float, float]              # unit tangent (launch direction)
    normal: Tuple[float, float]               # unit normal (perpendicular)

    # Lengths
    L_overlap_m: float      # input overlap (not RF body)
    L_body_m: float         # RF Klopfenstein body
    L_landing_m: float      # output landing (not RF body)
    L_total_m: float        # overlap + body + landing

    # Widths
    w_start_m: float        # input width (= selected track width)
    w_end_m: float          # output width (from RF synthesis)

    # Layer / net
    layer: str = "F.Cu"
    net_name: str = ""

    # Warnings / info
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    def debug_summary(self) -> str:
        """Human-readable debug string for logging before insertion."""
        lines = [
            "=== ONE-TRACE KLOPFENSTEIN LAUNCH ===",
            f"  Launch point:    ({self.launch_xy_m[0]*1e3:.3f}, {self.launch_xy_m[1]*1e3:.3f}) mm",
            f"  Direction:       ({self.tangent[0]:.4f}, {self.tangent[1]:.4f})",
            f"  Output end:      ({self.predicted_end_xy_m[0]*1e3:.3f}, {self.predicted_end_xy_m[1]*1e3:.3f}) mm",
            f"  L_overlap:       {self.L_overlap_m*1e3:.4f} mm",
            f"  L_body (RF):     {self.L_body_m*1e3:.3f} mm",
            f"  L_landing:       {self.L_landing_m*1e3:.4f} mm",
            f"  L_total:         {self.L_total_m*1e3:.3f} mm",
            f"  w_start:         {self.w_start_m*1e3:.4f} mm",
            f"  w_end:           {self.w_end_m*1e3:.4f} mm",
            f"  Layer:           {self.layer}",
            f"  Net:             '{self.net_name}'",
            f"  Polygon verts:   {len(self.polygon.outline)}",
        ]
        xs = [p[0] for p in self.polygon.outline]
        ys = [p[1] for p in self.polygon.outline]
        lines.append(f"  BBox X:          [{min(xs)*1e3:.3f}, {max(xs)*1e3:.3f}] mm")
        lines.append(f"  BBox Y:          [{min(ys)*1e3:.3f}, {max(ys)*1e3:.3f}] mm")

        if self.warnings:
            lines.append("  WARNINGS:")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")
        if self.info:
            lines.append("  INFO:")
            for i in self.info:
                lines.append(f"    • {i}")
        lines.append("=== END ===")
        return "\n".join(lines)


def prepare_insertion(
    profile: KlopfensteinProfile,
    selection: SelectionResult,
    overlap_m: float = None,
    landing_m: float = None,
) -> InsertionPlan:
    """Prepare a one-trace Klopfenstein launch polygon in board coordinates.

    Parameters
    ----------
    profile : KlopfensteinProfile
        Synthesized taper profile with layout-realized widths.
    selection : SelectionResult
        One-track selection with launch endpoint.
    overlap_m : float, optional
        Input overlap length.  Default: max(0.5*w_start, 50µm).
    landing_m : float, optional
        Output landing length.  Default: max(0.5*w_end, 50µm).

    Returns
    -------
    InsertionPlan
    """
    warnings: List[str] = []
    info: List[str] = []

    # ── Launch point and direction ──
    lx = selection.launch_x_m
    ly = selection.launch_y_m

    angle_rad = math.radians(selection.launch_tangent_deg)
    tx = math.cos(angle_rad)
    ty = math.sin(angle_rad)
    # Normal (perpendicular, 90° CCW)
    nx, ny = -ty, tx

    # ── Widths ──
    w_start = float(profile.w_layout[0])
    w_end = float(profile.w_layout[-1])

    # Width mismatch check
    w_track = selection.track_width_m
    if w_track > 0 and abs(w_start - w_track) / max(w_track, 1e-9) > 0.05:
        warnings.append(
            f"Taper start width ({w_start*1e3:.4f} mm) differs from selected "
            f"track width ({w_track*1e3:.4f} mm). "
            f"Selected ZS may not match actual trace impedance."
        )

    # ── Section lengths ──
    L_body = float(profile.L)

    if overlap_m is None:
        L_overlap = max(0.5 * w_start, 50e-6)
    else:
        L_overlap = float(overlap_m)

    if landing_m is None:
        L_landing = max(0.5 * w_end, 50e-6)
    else:
        L_landing = float(landing_m)

    L_total = L_overlap + L_body + L_landing

    info.append(
        f"RF body: {L_body*1e3:.3f} mm, "
        f"overlap: {L_overlap*1e6:.0f} µm, "
        f"landing: {L_landing*1e6:.0f} µm, "
        f"total: {L_total*1e3:.3f} mm"
    )

    # ── Generate composite polygon in board coordinates ──
    z_samples = profile.z_samples   # 0..L_body
    w_layout = profile.w_layout
    n = len(z_samples)

    left_edge: list = []
    right_edge: list = []

    # Section 1: Input overlap (constant width = w_start)
    # Goes from s = -L_overlap to s = 0 (backward from launch point)
    _add_constant_section(left_edge, right_edge,
                          lx, ly, tx, ty, nx, ny,
                          s_start=-L_overlap, s_end=0.0,
                          width=w_start, n_pts=3)

    # Section 2: RF Klopfenstein body
    # Goes from s = 0 to s = L_body
    for i in range(n):
        s = float(z_samples[i])
        w = float(w_layout[i])
        cx = lx + s * tx
        cy = ly + s * ty
        hw = w / 2.0
        left_edge.append((cx + hw * nx, cy + hw * ny))
        right_edge.append((cx - hw * nx, cy - hw * ny))

    # Section 3: Output landing (constant width = w_end)
    # Goes from s = L_body to s = L_body + L_landing
    _add_constant_section(left_edge, right_edge,
                          lx, ly, tx, ty, nx, ny,
                          s_start=L_body, s_end=L_body + L_landing,
                          width=w_end, n_pts=3)

    # Closed polygon: left forward + right reverse
    outline = left_edge + list(reversed(right_edge))

    # Predicted end point (where user routes from)
    end_x = lx + (L_body + L_landing) * tx
    end_y = ly + (L_body + L_landing) * ty

    polygon = TaperPolygon(
        left_edge=left_edge,
        right_edge=right_edge,
        outline=outline,
        centerline_z_m=z_samples.copy(),
        centerline_w_m=w_layout.copy(),
        length_m=L_body,
    )

    plan = InsertionPlan(
        polygon=polygon,
        launch_xy_m=(lx, ly),
        predicted_end_xy_m=(end_x, end_y),
        tangent=(tx, ty),
        normal=(nx, ny),
        L_overlap_m=L_overlap,
        L_body_m=L_body,
        L_landing_m=L_landing,
        L_total_m=L_total,
        w_start_m=w_start,
        w_end_m=w_end,
        layer=selection.layer,
        net_name=selection.net_name,
        warnings=warnings,
        info=info,
    )

    logger.info(plan.debug_summary())
    return plan


def _add_constant_section(left_edge, right_edge,
                          ox, oy, tx, ty, nx, ny,
                          s_start, s_end, width, n_pts=3):
    """Add constant-width polygon points along the tangent direction."""
    hw = width / 2.0
    for i in range(n_pts):
        frac = i / max(n_pts - 1, 1)
        s = s_start + frac * (s_end - s_start)
        cx = ox + s * tx
        cy = oy + s * ty
        left_edge.append((cx + hw * nx, cy + hw * ny))
        right_edge.append((cx - hw * nx, cy - hw * ny))
