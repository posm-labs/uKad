"""Abstract solver adapter interface.

All EM solver backends implement this interface.
The fast (non-EM) prediction path does NOT use this interface —
it uses taper_assembly.py directly.

This is the adapter pattern: rfcore defines what it needs,
and each backend translates to its native API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np


@dataclass
class SolverResult:
    """Result from an EM solver run."""
    freqs: np.ndarray             # frequency array (Hz)
    s_params: np.ndarray          # shape (n_freq, 2, 2) complex
    solve_time_s: float           # wall-clock time in seconds
    mesh_cells: int               # number of mesh cells used
    converged: bool               # solver convergence flag
    solver_name: str              # "openems", "openparemfd", etc.
    metadata: Dict = None         # solver-specific metadata

    @property
    def s11_db(self) -> np.ndarray:
        return 20.0 * np.log10(np.maximum(np.abs(self.s_params[:, 0, 0]), 1e-30))

    @property
    def s21_db(self) -> np.ndarray:
        return 20.0 * np.log10(np.maximum(np.abs(self.s_params[:, 1, 0]), 1e-30))


class SolverAdapter(ABC):
    """Abstract base for EM solver backends."""

    @abstractmethod
    def setup(self, geometry_dict: Dict, settings_dict: Dict) -> None:
        """Configure the solver with geometry and settings.

        Parameters
        ----------
        geometry_dict : dict
            Taper geometry (segment widths, lengths, pad/via geometry).
        settings_dict : dict
            Frequency range, mesh hints, boundary conditions.
        """
        ...

    @abstractmethod
    def run(self) -> SolverResult:
        """Execute the EM simulation and return results."""
        ...

    @abstractmethod
    def export_script(self, path: str) -> None:
        """Export a standalone simulation script to the given path.

        The script should be runnable without rfcore installed.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable solver name."""
        ...
