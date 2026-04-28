"""Track selection and geometry inference for KiCad PCB editor.

v1 workflow: ONE-TRACE KLOPFENSTEIN LAUNCH

User selects exactly one input track.  The plugin infers the launch
endpoint, width, layer, net, and direction.  No output trace is needed.

All KiCad interaction goes through ``addon.kicad_compat`` — this module
does NOT import ``pcbnew`` directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SelectionResult:
    """Result of inferring launch geometry from board selection.

    Coordinates are in metres.  Angles are in degrees.
    """
    mode: str = "manual"        # "auto" or "manual"
    valid: bool = False         # True if enough info to proceed

    # Layer / net
    layer: str = "F.Cu"
    net_name: str = ""

    # Launch point — free endpoint of the selected track (metres)
    launch_x_m: float = 0.0
    launch_y_m: float = 0.0

    # Launch direction — tangent pointing away from track (degrees)
    launch_tangent_deg: float = 0.0

    # Track width at launch endpoint (metres)
    track_width_m: float = 0.0

    # Info / warnings
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)


def infer_from_selection(board) -> SelectionResult:
    """Infer taper launch geometry from current board selection.

    Requires exactly 1 selected track segment.
    The launch point is the track's free end (the endpoint NOT shared
    with another track on the board).

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
        result.warnings.append("No tracks selected. Select one input track.")
        return result

    if len(selected) > 1:
        result.warnings.append(
            f"{len(selected)} tracks selected — select exactly 1 input track. "
            f"Using first selected track."
        )

    t = selected[0]

    result.layer = t.layer_name
    result.net_name = t.net_name
    result.track_width_m = to_m(t.width)

    # ── Find the free endpoint ──
    # The "free end" is the endpoint of the selected track that is NOT
    # shared with any other track on the same layer.  The taper launches
    # from this free end outward.
    start = (t.start_x, t.start_y)
    end = (t.end_x, t.end_y)

    start_connected = _is_endpoint_connected(board, t, start)
    end_connected = _is_endpoint_connected(board, t, end)

    if start_connected and not end_connected:
        # End is free — launch from end, direction = start→end
        launch = end
        anchor = start
    elif end_connected and not start_connected:
        # Start is free — launch from start, direction = end→start
        launch = start
        anchor = end
    elif not start_connected and not end_connected:
        # Neither connected — use end as launch (arbitrary, warn)
        launch = end
        anchor = start
        result.warnings.append(
            "Neither track endpoint is connected to other copper. "
            "Launching from track end point. Override direction if needed."
        )
    else:
        # Both connected — use end as launch (arbitrary, warn)
        launch = end
        anchor = start
        result.warnings.append(
            "Both track endpoints are connected to other copper. "
            "Launching from track end point. Override direction if needed."
        )

    result.launch_x_m = to_m(launch[0])
    result.launch_y_m = to_m(launch[1])

    # Tangent direction: from anchor toward launch point (pointing outward)
    dx = launch[0] - anchor[0]
    dy = launch[1] - anchor[1]
    if abs(dx) > 0 or abs(dy) > 0:
        result.launch_tangent_deg = math.degrees(math.atan2(dy, dx))
    else:
        result.launch_tangent_deg = 0.0
        result.warnings.append("Track has zero length. Direction defaulting to 0°.")

    result.mode = "auto"
    result.valid = True

    result.info.append(
        f"Auto: {result.layer}, net='{result.net_name}', "
        f"w={result.track_width_m*1e3:.4f}mm, "
        f"launch=({result.launch_x_m*1e3:.2f}, {result.launch_y_m*1e3:.2f})mm, "
        f"dir={result.launch_tangent_deg:.1f}°"
    )

    return result


def _is_endpoint_connected(board, track_info, endpoint_iu) -> bool:
    """Check if a track endpoint is shared with another track on the board."""
    from addon.kicad_compat import get_all_tracks

    ex, ey = endpoint_iu
    # Tolerance: 1 IU (1 nm)
    tol = 1

    for other in get_all_tracks(board):
        # Skip self
        if (other.start_x == track_info.start_x and
            other.start_y == track_info.start_y and
            other.end_x == track_info.end_x and
            other.end_y == track_info.end_y and
            other.width == track_info.width):
            continue

        # Same layer check
        if other.layer_name != track_info.layer_name:
            continue

        # Check if any endpoint of other track matches
        if (abs(other.start_x - ex) <= tol and abs(other.start_y - ey) <= tol):
            return True
        if (abs(other.end_x - ex) <= tol and abs(other.end_y - ey) <= tol):
            return True

    return False


def manual_selection(
    launch_x_mm: float, launch_y_mm: float,
    track_width_mm: float,
    angle_deg: float = 0.0,
    layer: str = "F.Cu",
    net_name: str = "",
) -> SelectionResult:
    """Create a SelectionResult from manual user input (for tests/headless).

    All coordinates and widths in mm.
    """
    return SelectionResult(
        mode="manual",
        valid=True,
        layer=layer,
        net_name=net_name,
        launch_x_m=launch_x_mm * 1e-3,
        launch_y_m=launch_y_mm * 1e-3,
        launch_tangent_deg=angle_deg,
        track_width_m=track_width_mm * 1e-3,
        info=[f"Manual: w={track_width_mm:.4f}mm, dir={angle_deg:.1f}°"],
    )
