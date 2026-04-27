"""Board insertion — writes taper geometry into KiCad board.

Primary method: net-assigned copper ZONE on the selected layer.
Fallback: PCB_SHAPE filled polygon (experimental).

All KiCad interaction goes through ``addon.kicad_compat`` — this module
does NOT import ``pcbnew`` directly.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from rfcore.export.geometry import TaperPolygon

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Primary: ZONE insertion
# ---------------------------------------------------------------------------

def insert_taper_zone(
    board,
    polygon: TaperPolygon,
    layer: str = "F.Cu",
    net_name: str = "",
) -> Any:
    """Insert taper as a net-assigned copper zone.

    The zone outline matches the layout-realized taper polygon exactly.
    Zone settings are configured to preserve the taper shape.

    Parameters
    ----------
    board
        The active KiCad board.
    polygon : TaperPolygon
        Taper polygon from geometry export.
    layer : str
        Copper layer name (e.g., "F.Cu").
    net_name : str
        Signal net name.

    Returns
    -------
    zone object (pcbnew.ZONE) — already added to the board.

    Raises
    ------
    RuntimeError
        If KiCad interaction fails.
    """
    from addon.kicad_compat import create_taper_zone, refill_zone

    try:
        zone = create_taper_zone(board, polygon.outline, layer, net_name)
        refill_zone(board, zone)
        return zone
    except Exception as e:
        raise RuntimeError(f"Failed to insert taper zone: {e}")


def get_zone_uuid(zone) -> str:
    """Return the UUID of an inserted zone for sidecar metadata."""
    from addon.kicad_compat import get_item_uuid_or_fallback
    return get_item_uuid_or_fallback(zone)
