"""openEMS solver adapter — stub for v1.

This module provides the interface for generating openEMS/CSXCAD simulation
scripts from taper geometry.  Full implementation is deferred to v1.1;
this stub defines the API surface and raises NotImplementedError.
"""

from __future__ import annotations

from typing import Dict

from rfcore.solver_base import SolverAdapter, SolverResult


class OpenEMSAdapter(SolverAdapter):
    """openEMS / CSXCAD solver adapter.

    Generates FDTD simulation geometry from taper assembly data.
    Requires openEMS and CSXCAD packages (optional dependency).
    """

    @property
    def name(self) -> str:
        return "openEMS"

    def setup(self, geometry_dict: Dict, settings_dict: Dict) -> None:
        """Configure openEMS simulation.

        Expected geometry_dict keys:
            segments: list of {z_start, z_end, w_rep} dicts
            substrate_height_m: float
            copper_thickness_m: float
            er: float
            pad_left: optional pad geometry dict
            pad_right: optional pad geometry dict
            via_left: optional via geometry dict
            via_right: optional via geometry dict

        Expected settings_dict keys:
            f_start_hz: float
            f_stop_hz: float
            n_points: int
            capture_margin_m: float
            port_extension_m: float
            mesh_density_hint: float
        """
        raise NotImplementedError(
            "openEMS adapter is not yet implemented in v1. "
            "Use the fast (non-EM) prediction path instead."
        )

    def run(self) -> SolverResult:
        raise NotImplementedError(
            "openEMS adapter is not yet implemented in v1."
        )

    def export_script(self, path: str) -> None:
        raise NotImplementedError(
            "openEMS script export is not yet implemented in v1."
        )
