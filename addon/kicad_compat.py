"""KiCad version compatibility layer.

All KiCad board interaction goes through this module.  No other file
in the project should import ``pcbnew`` directly.

Supported targets
-----------------
* **KiCad 8** — primary, fully tested (pcbnew SWIG bindings).
* **KiCad 9** — future, pcbnew still available (deprecated but functional).
* **KiCad 10+** — future, will require kicad-python IPC backend swap here.

Runtime detection
-----------------
``kicad_version()`` returns ``(major, minor, patch)``.  Every public
function in this module works identically regardless of version; internal
code-paths branch where the API surface differs.

Design rule
-----------
Nothing outside ``addon/kicad_compat.py`` may touch ``pcbnew``.
If a new KiCad operation is needed, add a wrapper here first.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy pcbnew import — fails gracefully outside KiCad
# ---------------------------------------------------------------------------
_pcbnew: Optional[Any] = None
_kicad_ver: Optional[Tuple[int, int, int]] = None


def _ensure_pcbnew():
    """Import pcbnew once and cache.  Raises RuntimeError outside KiCad."""
    global _pcbnew
    if _pcbnew is not None:
        return _pcbnew
    try:
        import pcbnew  # type: ignore
        _pcbnew = pcbnew
        return _pcbnew
    except ImportError:
        raise RuntimeError(
            "pcbnew module is not available.  "
            "This function must be called inside KiCad's Python environment."
        )


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def kicad_version() -> Tuple[int, int, int]:
    """Return ``(major, minor, patch)`` for the running KiCad.

    Returns (0, 0, 0) if detection fails.
    """
    global _kicad_ver
    if _kicad_ver is not None:
        return _kicad_ver

    pcbnew = _ensure_pcbnew()
    try:
        ver_str = pcbnew.GetBuildVersion()  # e.g. "8.0.5" or "9.0.1-..."
        parts = ver_str.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        # patch may have trailing text like "1-rc1"
        patch_str = parts[2].split("-")[0] if len(parts) > 2 else "0"
        patch = int(patch_str)
        _kicad_ver = (major, minor, patch)
    except Exception:
        _kicad_ver = (0, 0, 0)
        logger.warning("Could not detect KiCad version; assuming unknown (0.0.0)")
    return _kicad_ver


def kicad_major() -> int:
    """Return the major KiCad version number (8, 9, …)."""
    return kicad_version()[0]


def is_kicad_8() -> bool:
    return kicad_major() == 8


def is_kicad_9_or_later() -> bool:
    return kicad_major() >= 9


# ---------------------------------------------------------------------------
# Board handle
# ---------------------------------------------------------------------------

def get_board():
    """Return the active board object (pcbnew.BOARD)."""
    pcbnew = _ensure_pcbnew()
    return pcbnew.GetBoard()


def get_board_filename(board) -> str:
    """Return the full path to the .kicad_pcb file."""
    pcbnew = _ensure_pcbnew()
    try:
        return board.GetFileName()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Unit helpers
#
# KiCad internal units are nanometres:
#   1 mm  = 1_000_000 IU
#   1 m   = 1_000_000_000 IU
#
# We do NOT use pcbnew.FromMM / pcbnew.ToMM because KiCad 8's SWIG
# wrapper rejects numpy scalar types even after float() coercion.
# Pure-Python arithmetic avoids this entirely.
# ---------------------------------------------------------------------------

_IU_PER_MM = 1_000_000
_IU_PER_M = 1_000_000_000


def to_mm(kicad_units: int) -> float:
    """Convert KiCad internal units to millimetres."""
    return float(kicad_units) / _IU_PER_MM


def from_mm(mm) -> int:
    """Convert millimetres to KiCad internal units."""
    return int(round(float(mm) * _IU_PER_MM))


def to_m(kicad_units: int) -> float:
    """Convert KiCad internal units to metres."""
    return float(kicad_units) / _IU_PER_M


def from_m(metres) -> int:
    """Convert metres to KiCad internal units."""
    return int(round(float(metres) * _IU_PER_M))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

@dataclass
class TrackInfo:
    """Plain data extracted from a KiCad track segment."""
    start_x: int           # KiCad internal units
    start_y: int
    end_x: int
    end_y: int
    width: int             # KiCad internal units
    layer_name: str
    net_name: str
    _raw: Any = None       # original pcbnew object, for internal use only


def get_selected_tracks(board) -> List[TrackInfo]:
    """Return geometry of all selected track segments.

    Works on KiCad 8 and 9 (both use ``GetTracks()`` + ``IsSelected()``).
    """
    pcbnew = _ensure_pcbnew()
    tracks: List[TrackInfo] = []

    for item in board.GetTracks():
        if not item.IsSelected():
            continue
        # Filter to straight tracks (exclude vias, arcs in v1)
        if not isinstance(item, pcbnew.PCB_TRACK):
            continue
        # On KiCad 8/9, PCB_VIA is a subclass of PCB_TRACK.
        # Reject vias explicitly.
        if isinstance(item, pcbnew.PCB_VIA):
            continue

        start = item.GetStart()
        end = item.GetEnd()

        tracks.append(TrackInfo(
            start_x=start.x,
            start_y=start.y,
            end_x=end.x,
            end_y=end.y,
            width=item.GetWidth(),
            layer_name=item.GetLayerName(),
            net_name=item.GetNetname(),
            _raw=item,
        ))

    return tracks


def get_all_tracks(board) -> List[TrackInfo]:
    """Return geometry of ALL track segments on the board (for connectivity checks)."""
    pcbnew = _ensure_pcbnew()
    tracks: List[TrackInfo] = []

    for item in board.GetTracks():
        if not isinstance(item, pcbnew.PCB_TRACK):
            continue
        if isinstance(item, pcbnew.PCB_VIA):
            continue

        start = item.GetStart()
        end = item.GetEnd()

        tracks.append(TrackInfo(
            start_x=start.x,
            start_y=start.y,
            end_x=end.x,
            end_y=end.y,
            width=item.GetWidth(),
            layer_name=item.GetLayerName(),
            net_name=item.GetNetname(),
        ))

    return tracks


# ---------------------------------------------------------------------------
# Net lookup
# ---------------------------------------------------------------------------

def find_net(board, net_name: str):
    """Find a net by name.  Returns the pcbnew net object or None."""
    pcbnew = _ensure_pcbnew()
    try:
        net = board.FindNet(net_name)
        if net is not None and net.GetNetname() == net_name:
            return net
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Layer lookup
# ---------------------------------------------------------------------------

def get_layer_id(board, layer_name: str) -> int:
    """Resolve a layer name (e.g. 'F.Cu') to a layer ID."""
    pcbnew = _ensure_pcbnew()
    try:
        # KiCad 8+
        return board.GetLayerID(layer_name)
    except Exception:
        # Fallback for common layers
        _LAYER_MAP = {
            "F.Cu": 0,
            "B.Cu": 31,
            "In1.Cu": 1,
            "In2.Cu": 2,
        }
        return _LAYER_MAP.get(layer_name, 0)


# ---------------------------------------------------------------------------
# Zone creation (primary taper insertion)
# ---------------------------------------------------------------------------

def create_taper_zone(
    board,
    polygon_pts_m: List[Tuple[float, float]],
    layer_name: str,
    net_name: str = "",
) -> Any:
    """Create a net-assigned copper zone with the given polygon outline.

    Parameters
    ----------
    board
        Active pcbnew board.
    polygon_pts_m : list of (x, y)
        Closed polygon vertices in **metres**.
    layer_name : str
        Copper layer, e.g. ``"F.Cu"``.
    net_name : str
        Signal net name (empty string for unassigned).

    Returns
    -------
    zone
        The pcbnew ZONE object (already added to the board, not yet filled).
    """
    pcbnew = _ensure_pcbnew()

    zone = pcbnew.ZONE(board)

    layer_id = get_layer_id(board, layer_name)
    zone.SetLayer(layer_id)

    zone.SetIsFilled(True)
    zone.SetIsRuleArea(False)

    # Net
    if net_name:
        net = find_net(board, net_name)
        if net:
            zone.SetNet(net)

    # Polygon outline — ensure every coordinate is native Python int
    outline = zone.Outline()
    outline.NewOutline()
    for x_m, y_m in polygon_pts_m:
        ix = from_m(x_m)
        iy = from_m(y_m)
        outline.Append(int(ix), int(iy))

    # Settings to preserve exact taper geometry.
    # Each call is guarded because KiCad 8/9 differ in available methods.
    try:
        zone.SetMinThickness(from_mm(0.01))
    except Exception:
        pass

    try:
        zone.SetLocalClearance(0)
    except Exception:
        pass

    # KiCad 8: SetZonePriority / SetAssignedPriority; KiCad 9: SetPriority
    for pri_method in ("SetPriority", "SetAssignedPriority", "SetZonePriority"):
        fn = getattr(zone, pri_method, None)
        if fn is not None:
            try:
                fn(100)
                break
            except Exception:
                continue

    # Pad connection — enum name varies across versions
    for conn_enum in ("ZONE_CONNECTION_FULL", "ZoneConnection_Full"):
        val = getattr(pcbnew, conn_enum, None)
        if val is not None:
            try:
                zone.SetPadConnection(val)
                break
            except Exception:
                continue

    board.Add(zone)
    return zone


def refill_zone(board, zone) -> None:
    """Refill a single zone.  Call after ``create_taper_zone``."""
    pcbnew = _ensure_pcbnew()
    try:
        # Fill ALL zones (matches working RF-tools pattern).
        # This is more reliable than filling a single zone.
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
    except Exception as e:
        logger.warning(f"Zone refill failed: {e}")


# ---------------------------------------------------------------------------
# Item identity (for sidecar metadata)
# ---------------------------------------------------------------------------

def get_item_uuid_or_fallback(item) -> str:
    """Return the KiCad internal UUID of a board item as a plain string.

    KiCad 8 returns a KIID object from m_Uuid — we call AsString() on it.
    """
    for attr in ("m_Uuid", "GetUUID", "GetKIID"):
        try:
            val = getattr(item, attr)
            if callable(val):
                val = val()
            # KIID objects have AsString(); plain strings don't
            if hasattr(val, 'AsString'):
                return val.AsString()
            return str(val)
        except Exception:
            continue
    return f"fallback-{id(item):016x}"


# ---------------------------------------------------------------------------
# Board refresh
# ---------------------------------------------------------------------------

def refresh_board() -> None:
    """Refresh the KiCad PCB editor display."""
    pcbnew = _ensure_pcbnew()
    try:
        pcbnew.Refresh()
    except AttributeError:
        # KiCad 8 may not have Refresh(); try alternatives
        try:
            board = pcbnew.GetBoard()
            board.GetDesignSettings()  # force re-read
        except Exception:
            pass


# ---------------------------------------------------------------------------
# wx parent window
# ---------------------------------------------------------------------------

def get_kicad_parent_window():
    """Return the KiCad main frame as a wx.Window, or None."""
    try:
        import wx
        # KiCad 8 window name
        parent = wx.FindWindowByName("PcbFrame")
        if parent is None:
            parent = wx.FindWindowByName("pcbnew_frame")
        return parent
    except Exception:
        return None
