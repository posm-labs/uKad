"""Board insertion — writes taper geometry back to KiCad board.

Creates track segments along the taper profile on the specified layer and net.
Preserves existing board content; only adds new tracks.

The taper is laid out as a series of straight track segments with
varying widths, approximating the continuous taper profile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from addon.ipc_client import KiCadConnection


@dataclass
class TaperTrackSegment:
    """One track segment of the taper to be placed on the board."""
    x_start_m: float
    y_start_m: float
    x_end_m: float
    y_end_m: float
    width_m: float
    layer: str = "F.Cu"
    net_name: str = ""


def generate_track_segments(
    z_positions_m: np.ndarray,
    widths_m: np.ndarray,
    origin_x_m: float,
    origin_y_m: float,
    angle_deg: float = 0.0,
    layer: str = "F.Cu",
    net_name: str = "",
) -> List[TaperTrackSegment]:
    """Generate track segments from taper profile data.

    The taper is placed starting at (origin_x, origin_y) and extending
    along the specified angle.

    Parameters
    ----------
    z_positions_m : array
        Position array along taper axis (m).
    widths_m : array
        Width array corresponding to z_positions (m).
    origin_x_m, origin_y_m : float
        Board coordinates for taper start (m).
    angle_deg : float
        Taper direction angle in degrees (0 = rightward, +X).
    layer : str
        Copper layer name (e.g., "F.Cu").
    net_name : str
        Signal net name.

    Returns
    -------
    list of TaperTrackSegment
    """
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    segments: List[TaperTrackSegment] = []
    n = len(z_positions_m)

    for i in range(n - 1):
        z0 = z_positions_m[i]
        z1 = z_positions_m[i + 1]
        w_avg = (widths_m[i] + widths_m[i + 1]) / 2.0

        x0 = origin_x_m + z0 * cos_a
        y0 = origin_y_m + z0 * sin_a
        x1 = origin_x_m + z1 * cos_a
        y1 = origin_y_m + z1 * sin_a

        segments.append(TaperTrackSegment(
            x_start_m=x0, y_start_m=y0,
            x_end_m=x1, y_end_m=y1,
            width_m=w_avg,
            layer=layer,
            net_name=net_name,
        ))

    return segments


def insert_taper_tracks(
    conn: KiCadConnection,
    segments: List[TaperTrackSegment],
) -> int:
    """Insert taper track segments into the KiCad board.

    Parameters
    ----------
    conn : KiCadConnection
        Active IPC connection.
    segments : list of TaperTrackSegment
        Track segments to add.

    Returns
    -------
    int
        Number of tracks successfully added.
    """
    board = conn.board
    added = 0

    try:
        from kicad.board import Track  # type: ignore

        for seg in segments:
            track = Track()
            # KiCad uses nanometres internally
            track.start.x = int(seg.x_start_m * 1e6)  # m → nm → KiCad units
            track.start.y = int(seg.y_start_m * 1e6)
            track.end.x = int(seg.x_end_m * 1e6)
            track.end.y = int(seg.y_end_m * 1e6)
            track.width = int(seg.width_m * 1e6)
            track.layer = seg.layer

            # Set net
            if seg.net_name:
                for net in board.nets:
                    if net.name == seg.net_name:
                        track.net = net
                        break

            board.add(track)
            added += 1

    except ImportError:
        raise RuntimeError(
            "kicad-python is not installed. Cannot insert tracks."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to insert tracks: {e}")

    return added
