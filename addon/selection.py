"""Track selection and geometry inference for KiCad PCB editor.

Reads the current board selection and infers taper endpoint geometry.

Mode A (automatic): Two tracks selected on same layer → infer everything.
Mode B (manual): Ambiguous selection → provide defaults for manual override.

All KiCad interaction goes through ``addon.kicad_compat`` — this module
does NOT import ``pcbnew`` directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class SelectionResult:
    """Result of inferring taper endpoints from board selection.

    Coordinates are in metres.  Angles are in degrees.
    """
    mode: str = "manual"        # "auto" or "manual"
    valid: bool = False         # True if enough info to proceed
    layer: str = "F.Cu"
    net_name: str = ""

    # Endpoint positions (metres)
    start_x_m: float = 0.0
    start_y_m: float = 0.0
    end_x_m: float = 0.0
    end_y_m: float = 0.0

    # Endpoint widths (metres)
    start_width_m: float = 0.0
    end_width_m: float = 0.0

    # Direction tangents (direction taper extends from each endpoint)
    start_tangent_deg: float = 0.0
    end_tangent_deg: float = 180.0

    # Computed properties
    distance_m: float = 0.0    # straight-line distance between endpoints

    # Info / warnings
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)


def infer_from_selection(board) -> SelectionResult:
    """Infer taper endpoints from current board selection.

    Requires exactly 2 track segments on the same copper layer.
    All KiCad interaction goes through ``addon.kicad_compat``.

    Parameters
    ----------
    board
        The active KiCad board (from ``kicad_compat.get_board()``).

    Returns
    -------
    SelectionResult
    """
    from addon.kicad_compat import get_selected_tracks, to_m

    result = SelectionResult()

    try:
        selected = get_selected_tracks(board)
    except RuntimeError as e:
        result.warnings.append(str(e))
        return result

    if len(selected) == 0:
        result.warnings.append("No tracks selected. Use manual mode.")
        return result

    if len(selected) == 1:
        t = selected[0]
        result.layer = t.layer_name
        result.net_name = t.net_name
        result.start_width_m = to_m(t.width)
        result.info.append(
            f"Single track selected: layer={result.layer}, "
            f"net={result.net_name}, width={result.start_width_m*1e3:.3f}mm. "
            f"Select a second track for automatic mode."
        )
        return result

    if len(selected) > 2:
        result.warnings.append(
            f"{len(selected)} tracks selected — expected 2. "
            f"Select exactly 2 tracks for automatic mode."
        )
        selected = selected[:2]

    t1, t2 = selected[0], selected[1]

    # Check same layer
    if t1.layer_name != t2.layer_name:
        result.warnings.append(
            f"Selected tracks are on different layers "
            f"({t1.layer_name}, {t2.layer_name}). "
            f"Taper requires same-layer tracks."
        )
        result.layer = t1.layer_name
        return result

    result.layer = t1.layer_name

    # Check net
    if t1.net_name and t2.net_name and t1.net_name != t2.net_name:
        result.warnings.append(
            f"Selected tracks have different nets "
            f"({t1.net_name}, {t2.net_name}). "
            f"Confirm the desired net."
        )
    result.net_name = t1.net_name or t2.net_name or ""

    # ── Find closest unconnected endpoints ──
    # Each track has (start, end).  We want the pair of endpoints
    # (one from each track) that are closest — those define the gap
    # where the taper will be inserted.
    endpoints = [
        ((t1.start_x, t1.start_y), (t1.end_x, t1.end_y),
         (t2.start_x, t2.start_y), (t2.end_x, t2.end_y)),
        ((t1.start_x, t1.start_y), (t1.end_x, t1.end_y),
         (t2.end_x, t2.end_y), (t2.start_x, t2.start_y)),
        ((t1.end_x, t1.end_y), (t1.start_x, t1.start_y),
         (t2.start_x, t2.start_y), (t2.end_x, t2.end_y)),
        ((t1.end_x, t1.end_y), (t1.start_x, t1.start_y),
         (t2.end_x, t2.end_y), (t2.start_x, t2.start_y)),
    ]

    best = None
    best_dist = float("inf")
    for gap1, anchor1, gap2, anchor2 in endpoints:
        dx = gap1[0] - gap2[0]
        dy = gap1[1] - gap2[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < best_dist:
            best_dist = dist
            best = (gap1, anchor1, gap2, anchor2)

    gap1, anchor1, gap2, anchor2 = best

    # Taper start = gap endpoint of track 1
    result.start_x_m = to_m(gap1[0])
    result.start_y_m = to_m(gap1[1])
    result.start_width_m = to_m(t1.width)

    # Taper end = gap endpoint of track 2
    result.end_x_m = to_m(gap2[0])
    result.end_y_m = to_m(gap2[1])
    result.end_width_m = to_m(t2.width)

    # Compute tangent directions
    dx1 = gap1[0] - anchor1[0]
    dy1 = gap1[1] - anchor1[1]
    result.start_tangent_deg = math.degrees(math.atan2(dy1, dx1))

    dx2 = gap2[0] - anchor2[0]
    dy2 = gap2[1] - anchor2[1]
    result.end_tangent_deg = math.degrees(math.atan2(dy2, dx2))

    # Distance
    dx = result.end_x_m - result.start_x_m
    dy = result.end_y_m - result.start_y_m
    result.distance_m = math.sqrt(dx * dx + dy * dy)

    result.mode = "auto"
    result.valid = True

    result.info.append(
        f"Auto mode: {result.layer}, net={result.net_name}, "
        f"distance={result.distance_m*1e3:.2f}mm, "
        f"w_start={result.start_width_m*1e3:.3f}mm, "
        f"w_end={result.end_width_m*1e3:.3f}mm"
    )

    return result


def manual_selection(
    start_x_mm: float, start_y_mm: float,
    end_x_mm: float, end_y_mm: float,
    start_width_mm: float, end_width_mm: float,
    layer: str = "F.Cu",
    net_name: str = "",
    angle_deg: float = 0.0,
) -> SelectionResult:
    """Create a SelectionResult from manual user input.

    All coordinates and widths in mm.
    """
    dx = (end_x_mm - start_x_mm) * 1e-3
    dy = (end_y_mm - start_y_mm) * 1e-3
    distance_m = math.sqrt(dx * dx + dy * dy)

    computed_angle = math.degrees(math.atan2(dy, dx)) if distance_m > 0 else angle_deg

    return SelectionResult(
        mode="manual",
        valid=True,
        layer=layer,
        net_name=net_name,
        start_x_m=start_x_mm * 1e-3,
        start_y_m=start_y_mm * 1e-3,
        end_x_m=end_x_mm * 1e-3,
        end_y_m=end_y_mm * 1e-3,
        start_width_m=start_width_mm * 1e-3,
        end_width_m=end_width_mm * 1e-3,
        start_tangent_deg=computed_angle,
        end_tangent_deg=computed_angle + 180.0,
        distance_m=distance_m,
        info=[f"Manual mode: distance={distance_m*1e3:.2f}mm"],
    )
