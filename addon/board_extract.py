"""Board geometry extraction — reads taper-relevant structures from KiCad board.

Extracts:
  - Endpoint traces (widths, positions)
  - Nearby pads (dimensions, drill, clearance)
  - Nearby vias (drill, diameter, layers)
  - Net connectivity context

Outputs data structures that rfcore can consume without any KiCad dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from addon.ipc_client import KiCadConnection, BoardQuery


@dataclass
class EndpointGeometry:
    """Geometry extracted for one taper endpoint from the board."""

    # Trace info
    trace_width_m: float = 0.0
    trace_layer: str = ""

    # Pad info (if a pad is present at this endpoint)
    has_pad: bool = False
    pad_width_m: float = 0.0
    pad_height_m: float = 0.0
    pad_drill_m: float = 0.0
    pad_shape: str = ""

    # Via info (if a via is within capture radius)
    has_via: bool = False
    via_drill_m: float = 0.0
    via_diameter_m: float = 0.0
    via_x_m: float = 0.0
    via_y_m: float = 0.0

    # Return via (nearest ground/return via)
    has_return_via: bool = False
    return_via_drill_m: float = 0.0
    return_via_distance_m: float = 0.0

    # Antipad (estimated from design rules if not available)
    antipad_diameter_m: float = 0.0


@dataclass
class TaperExtractionResult:
    """Result of extracting taper-relevant geometry from the board."""

    net_name: str
    start_endpoint: EndpointGeometry
    end_endpoint: EndpointGeometry
    trace_widths_m: List[float] = field(default_factory=list)
    board_filename: str = ""
    warnings: List[str] = field(default_factory=list)


def extract_taper_context(
    conn: KiCadConnection,
    net_name: str,
    start_xy: Tuple[float, float],
    end_xy: Tuple[float, float],
    capture_radius_m: float = 2.0e-3,
    substrate_height_m: float = 0.254e-3,
) -> TaperExtractionResult:
    """Extract taper-relevant geometry from the board around two endpoints.

    Parameters
    ----------
    conn : KiCadConnection
        Active IPC connection.
    net_name : str
        Signal net name.
    start_xy : (float, float)
        Approximate (x, y) position of taper start in metres.
    end_xy : (float, float)
        Approximate (x, y) position of taper end in metres.
    capture_radius_m : float
        Radius around each endpoint to search for pads/vias.
    substrate_height_m : float
        Substrate height for via inclusion rule (3h distance).

    Returns
    -------
    TaperExtractionResult
    """
    query = BoardQuery(conn)
    result = TaperExtractionResult(
        net_name=net_name,
        start_endpoint=EndpointGeometry(),
        end_endpoint=EndpointGeometry(),
    )

    try:
        result.board_filename = query.get_board_filename()
    except Exception:
        pass

    # Get tracks on this net
    tracks = query.get_tracks_on_net(net_name)
    result.trace_widths_m = list({t["width_m"] for t in tracks})

    # Get pads on this net
    pads = query.get_pads_on_net(net_name)

    # Get vias on this net
    vias_on_net = query.get_vias_on_net(net_name)

    # For each endpoint, find nearest pad and via
    for ep_xy, ep in [(start_xy, result.start_endpoint),
                       (end_xy, result.end_endpoint)]:

        # Find nearest track for width
        nearest_track_dist = float("inf")
        for t in tracks:
            mid_x = (t["start_x_m"] + t["end_x_m"]) / 2
            mid_y = (t["start_y_m"] + t["end_y_m"]) / 2
            d = math.sqrt((mid_x - ep_xy[0])**2 + (mid_y - ep_xy[1])**2)
            if d < nearest_track_dist:
                nearest_track_dist = d
                ep.trace_width_m = t["width_m"]
                ep.trace_layer = t["layer"]

        # Find nearest pad within capture radius
        for p in pads:
            d = math.sqrt((p["x_m"] - ep_xy[0])**2 + (p["y_m"] - ep_xy[1])**2)
            if d < capture_radius_m:
                ep.has_pad = True
                ep.pad_width_m = p["width_m"]
                ep.pad_height_m = p["height_m"]
                ep.pad_drill_m = p.get("drill_m", 0.0)
                ep.pad_shape = p.get("shape", "")

        # Find signal via within 3·h (hard inclusion rule)
        via_inclusion_dist = 3.0 * substrate_height_m
        for v in vias_on_net:
            d = math.sqrt((v["x_m"] - ep_xy[0])**2 + (v["y_m"] - ep_xy[1])**2)
            if d < via_inclusion_dist:
                ep.has_via = True
                ep.via_drill_m = v["drill_m"]
                ep.via_diameter_m = v["diameter_m"]
                ep.via_x_m = v["x_m"]
                ep.via_y_m = v["y_m"]
                # Estimate antipad as 2× via diameter (conservative default)
                ep.antipad_diameter_m = v["diameter_m"] * 2.0
            elif d < 10.0 * substrate_height_m:
                result.warnings.append(
                    f"WARNING: Via at ({v['x_m']*1e3:.2f}, {v['y_m']*1e3:.2f}) mm "
                    f"is {d/substrate_height_m:.1f}·h from endpoint — "
                    f"within warning zone (3h–10h) but outside inclusion zone."
                )

        # Find nearest return via (any net that isn't the signal net,
        # or ground net heuristic)
        # In v1, we search all vias and pick closest non-signal via
        try:
            all_board_vias = []
            for via in conn.board.vias:
                if via.net.name != net_name:
                    vx = via.position.x * 1e-6
                    vy = via.position.y * 1e-6
                    d = math.sqrt((vx - ep_xy[0])**2 + (vy - ep_xy[1])**2)
                    all_board_vias.append((d, via.drill * 1e-6))

            if all_board_vias:
                all_board_vias.sort(key=lambda x: x[0])
                nearest_d, nearest_drill = all_board_vias[0]
                if nearest_d < 10.0 * substrate_height_m:
                    ep.has_return_via = True
                    ep.return_via_drill_m = nearest_drill
                    ep.return_via_distance_m = nearest_d
        except Exception:
            pass

        if not ep.has_return_via:
            result.warnings.append(
                f"WARNING: No return via found near endpoint "
                f"({ep_xy[0]*1e3:.2f}, {ep_xy[1]*1e3:.2f}) mm. "
                f"Return-path model will use spreading approximation "
                f"(low confidence)."
            )

    return result
