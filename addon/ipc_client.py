"""KiCad IPC client — thin wrapper over kicad-python.

This module handles all communication with a running KiCad 9+ instance
through the IPC API.  No RF modeling code lives here.

The IPC API uses gRPC under the hood.  This module abstracts the
connection lifecycle and provides typed helpers for the operations
that the taper tool needs.

Requires: kicad-python >= 0.1 (optional dependency)
Requires: KiCad 9+ running with IPC API enabled
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection wrapper
# ---------------------------------------------------------------------------

class KiCadIPCError(Exception):
    """Raised when IPC communication fails."""
    pass


class KiCadConnection:
    """Manages connection to a running KiCad instance.

    Usage::

        conn = KiCadConnection()
        conn.connect()
        board = conn.get_board()
        conn.disconnect()

    Or as context manager::

        with KiCadConnection() as conn:
            board = conn.get_board()
    """

    def __init__(self, host: str = "localhost", port: int = 0) -> None:
        self._host = host
        self._port = port
        self._board = None
        self._connected = False

    def connect(self) -> None:
        """Connect to the KiCad IPC API."""
        try:
            from kicad import KiCad  # type: ignore
            self._kicad = KiCad()
            self._board = self._kicad.get_board()
            self._connected = True
            logger.info("Connected to KiCad IPC API")
        except ImportError:
            raise KiCadIPCError(
                "kicad-python is not installed. "
                "Install with: pip install kicad-python"
            )
        except Exception as e:
            raise KiCadIPCError(
                f"Failed to connect to KiCad IPC API: {e}. "
                f"Ensure KiCad 9+ is running with the IPC API enabled."
            )

    def disconnect(self) -> None:
        self._board = None
        self._connected = False
        logger.info("Disconnected from KiCad IPC API")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def board(self):
        """The active kicad Board object."""
        if not self._connected or self._board is None:
            raise KiCadIPCError("Not connected to KiCad.")
        return self._board

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()


# ---------------------------------------------------------------------------
# Board query helpers
# ---------------------------------------------------------------------------

class BoardQuery:
    """Read-only queries against the KiCad board."""

    def __init__(self, conn: KiCadConnection) -> None:
        self._conn = conn

    def get_board_filename(self) -> str:
        """Return the .kicad_pcb filename."""
        return str(self._conn.board.file_path)

    def get_stackup_info(self) -> Dict[str, Any]:
        """Extract stackup information from the board.

        Returns a dict with layer names, types, and thicknesses
        as available from the board setup.
        """
        board = self._conn.board
        info: Dict[str, Any] = {"layers": []}
        try:
            setup = board.design_settings
            info["board_thickness_m"] = setup.board_thickness * 1e-6  # KiCad uses nm internally
        except Exception:
            pass
        return info

    def get_nets(self) -> List[str]:
        """Return all net names on the board."""
        return [net.name for net in self._conn.board.nets]

    def get_tracks_on_net(self, net_name: str) -> List[Dict[str, Any]]:
        """Return track segments on a given net.

        Each track is returned as a dict with:
          start_x_m, start_y_m, end_x_m, end_y_m, width_m, layer
        """
        tracks = []
        for track in self._conn.board.tracks:
            if track.net.name == net_name:
                tracks.append({
                    "start_x_m": track.start.x * 1e-6,
                    "start_y_m": track.start.y * 1e-6,
                    "end_x_m": track.end.x * 1e-6,
                    "end_y_m": track.end.y * 1e-6,
                    "width_m": track.width * 1e-6,
                    "layer": track.layer,
                })
        return tracks

    def get_pads_on_net(self, net_name: str) -> List[Dict[str, Any]]:
        """Return pads on a given net."""
        pads = []
        for fp in self._conn.board.footprints:
            for pad in fp.pads:
                if pad.net.name == net_name:
                    pads.append({
                        "x_m": pad.position.x * 1e-6,
                        "y_m": pad.position.y * 1e-6,
                        "width_m": pad.size.x * 1e-6,
                        "height_m": pad.size.y * 1e-6,
                        "drill_m": (pad.drill.x * 1e-6) if pad.drill else 0.0,
                        "shape": str(pad.shape),
                        "layers": [str(l) for l in pad.layers],
                    })
        return pads

    def get_vias_on_net(self, net_name: str) -> List[Dict[str, Any]]:
        """Return vias on a given net."""
        vias = []
        for via in self._conn.board.vias:
            if via.net.name == net_name:
                vias.append({
                    "x_m": via.position.x * 1e-6,
                    "y_m": via.position.y * 1e-6,
                    "drill_m": via.drill * 1e-6,
                    "diameter_m": via.width * 1e-6,
                    "start_layer": str(via.start_layer),
                    "end_layer": str(via.end_layer),
                })
        return vias
