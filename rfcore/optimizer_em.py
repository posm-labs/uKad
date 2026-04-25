"""EM-backed optimizer — stub for v1.

This module will wrap the SolverAdapter interface to run EM-in-the-loop
optimization.  The fast optimizer (optimizer_fast.py) is used for the
initial parameter search; the EM optimizer refines selected points.

Not implemented in v1.  The API surface is defined here so that
the addon and report modules can reference it without import errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from rfcore.config import RFProjectSettings
from rfcore.solver_base import SolverAdapter, SolverResult
from rfcore.taper_assembly import AssemblyResult


@dataclass
class EMOptimizerResult:
    """Result from EM-backed optimization."""
    fast_result: AssemblyResult          # fast-model result at optimum
    em_result: Optional[SolverResult]    # EM result at optimum (None in v1)
    n_em_evals: int
    converged: bool


def optimize_em(
    settings: RFProjectSettings,
    solver: SolverAdapter,
    fast_result: AssemblyResult,
) -> EMOptimizerResult:
    """Run EM-backed optimization.

    Not implemented in v1.

    Parameters
    ----------
    settings : RFProjectSettings
    solver : SolverAdapter
        Configured EM solver backend.
    fast_result : AssemblyResult
        Result from the fast optimizer (starting point).

    Raises
    ------
    NotImplementedError
        Always, in v1.
    """
    raise NotImplementedError(
        "EM-backed optimization is not implemented in v1. "
        "Use optimizer_fast.optimize_taper() for non-EM optimization."
    )
