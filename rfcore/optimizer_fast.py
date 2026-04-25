"""Fast (non-EM) taper optimizer.

Default mode: direct Klopfenstein synthesis with no optimization.
Optimizer is invoked explicitly by the user.

Free variables (when optimizer runs):
  - L (taper length): [L_min, 5·L_min]
  - left_trim_m: [0, 2·h]
  - right_trim_m: [0, 2·h]

Locked by default:
  - Gamma_m (must be explicitly unlocked by user)
  - Pad/via parameters

Algorithm: Differential Evolution (global) → Powell (local polish).

Objective:
  J = w1·max|S11| + w2·IL_penalty + w3·(L/L_min - 1) + w4·mfg_penalty
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np
from scipy.optimize import differential_evolution, minimize

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import TaperAssembly, AssemblyResult
from rfcore.discontinuities.base import DiscontinuityBlock


@dataclass
class OptimizerConfig:
    """Optimizer configuration."""

    # Objective weights
    w_s11: float = 1.0           # weight on max |S11| (dB, made positive for minimization)
    w_insertion_loss: float = 0.5  # weight on worst-case IL above baseline
    w_length: float = 0.1         # weight on L/L_min - 1
    w_mfg: float = 0.2           # manufacturing penalty (min feature size)

    # Free variables
    optimize_length: bool = True
    optimize_left_trim: bool = True
    optimize_right_trim: bool = True
    optimize_gamma_m: bool = False   # LOCKED by default

    # Algorithm
    de_maxiter: int = 50
    de_popsize: int = 15
    de_tol: float = 0.01
    powell_maxiter: int = 100

    # Constraints
    min_feature_m: float = 75e-6   # 75 μm min width/space (3 mil)


@dataclass
class OptimizerResult:
    """Result of fast optimization."""

    # Best parameters found
    L_opt: float
    left_trim_opt: float
    right_trim_opt: float
    Gamma_m_opt: float

    # Performance metrics
    objective_initial: float
    objective_final: float
    s11_max_initial_db: float
    s11_max_final_db: float

    # Assembly result at optimum
    assembly_result: AssemblyResult

    # Convergence info
    n_evals: int
    converged: bool


def optimize_taper(
    settings: RFProjectSettings,
    microstrip: MicrostripModel,
    ZS: float,
    ZL: float,
    Gamma_m: float,
    left_chain: Optional[List[DiscontinuityBlock]] = None,
    right_chain: Optional[List[DiscontinuityBlock]] = None,
    config: Optional[OptimizerConfig] = None,
) -> OptimizerResult:
    """Run fast taper optimization.

    Parameters
    ----------
    settings : RFProjectSettings
    microstrip : MicrostripModel
    ZS, ZL : float
        Endpoint impedances (Ω).
    Gamma_m : float
        Target passband reflection coefficient (fixed unless unlocked).
    left_chain, right_chain : list of DiscontinuityBlock
        Endpoint discontinuity blocks (fixed during optimization).
    config : OptimizerConfig
        Optimizer settings.

    Returns
    -------
    OptimizerResult
    """
    if config is None:
        config = OptimizerConfig()

    h = settings.stackup.substrate_height_m
    f_min = settings.analysis.f_start_hz
    f_geom = settings.analysis.f_geom

    # Compute L_min for reference
    profile_ref = KlopfensteinProfile(
        ZS=ZS, ZL=ZL, Gamma_m=Gamma_m,
        microstrip=microstrip, f_min=f_min, f_geom=f_geom,
    )
    L_min = profile_ref.L

    # Build variable bounds
    bounds: List[Tuple[float, float]] = []
    var_names: List[str] = []

    if config.optimize_length:
        bounds.append((L_min, 5.0 * L_min))
        var_names.append("L")
    if config.optimize_left_trim:
        bounds.append((0.0, 2.0 * h))
        var_names.append("left_trim")
    if config.optimize_right_trim:
        bounds.append((0.0, 2.0 * h))
        var_names.append("right_trim")
    if config.optimize_gamma_m:
        bounds.append((Gamma_m * 0.5, min(Gamma_m * 2.0, 0.5)))
        var_names.append("Gamma_m")

    if not bounds:
        # Nothing to optimize — just evaluate
        assembly = TaperAssembly(
            settings, profile_ref, microstrip, left_chain, right_chain,
        )
        result = assembly.evaluate()
        return OptimizerResult(
            L_opt=profile_ref.L,
            left_trim_opt=0.0,
            right_trim_opt=0.0,
            Gamma_m_opt=Gamma_m,
            objective_initial=0.0,
            objective_final=0.0,
            s11_max_initial_db=float(np.max(result.s11_db)),
            s11_max_final_db=float(np.max(result.s11_db)),
            assembly_result=result,
            n_evals=1,
            converged=True,
        )

    eval_count = [0]

    def unpack(x: np.ndarray) -> dict:
        d = {}
        idx = 0
        for name in var_names:
            d[name] = x[idx]
            idx += 1
        return d

    def objective(x: np.ndarray) -> float:
        eval_count[0] += 1
        params = unpack(x)

        L = params.get("L", L_min)
        gm = params.get("Gamma_m", Gamma_m)

        try:
            profile = KlopfensteinProfile(
                ZS=ZS, ZL=ZL, Gamma_m=gm,
                microstrip=microstrip, L=L, f_min=f_min, f_geom=f_geom,
            )
        except (ValueError, RuntimeError):
            return 1e6  # infeasible

        assembly = TaperAssembly(
            settings, profile, microstrip, left_chain, right_chain,
        )
        result = assembly.evaluate()

        # Objective components
        s11_max = float(np.max(result.s11_db))  # dB, negative is good
        il_worst = float(-np.min(result.s21_db))  # positive = loss in dB
        length_penalty = (L / L_min - 1.0) if L_min > 0 else 0.0

        # Manufacturing penalty
        w_min = float(np.min(profile.w_profile))
        mfg_penalty = max(0, config.min_feature_m - w_min) / config.min_feature_m

        # Compose (we want to MINIMIZE, so make S11 positive = worse)
        J = (config.w_s11 * (s11_max + 40) / 40  # normalize: -40dB → 0, 0dB → 1
             + config.w_insertion_loss * il_worst / 3.0  # normalize: 3dB → 1
             + config.w_length * length_penalty
             + config.w_mfg * mfg_penalty)

        return J

    # Initial objective
    x0 = []
    for name, (lo, hi) in zip(var_names, bounds):
        if name == "L":
            x0.append(L_min)
        elif name == "Gamma_m":
            x0.append(Gamma_m)
        else:
            x0.append(0.0)
    x0 = np.array(x0)
    obj_initial = objective(x0)

    # Evaluate initial S11
    assembly_init = TaperAssembly(
        settings, profile_ref, microstrip, left_chain, right_chain,
    )
    result_init = assembly_init.evaluate()
    s11_initial = float(np.max(result_init.s11_db))

    # Differential Evolution (global)
    de_result = differential_evolution(
        objective,
        bounds=bounds,
        maxiter=config.de_maxiter,
        popsize=config.de_popsize,
        tol=config.de_tol,
        seed=42,
    )

    # Powell (local refinement)
    powell_result = minimize(
        objective,
        de_result.x,
        method='Powell',
        bounds=bounds,
        options={'maxiter': config.powell_maxiter},
    )

    best_x = powell_result.x
    best_params = unpack(best_x)

    # Final evaluation at optimum
    L_final = best_params.get("L", L_min)
    gm_final = best_params.get("Gamma_m", Gamma_m)
    profile_final = KlopfensteinProfile(
        ZS=ZS, ZL=ZL, Gamma_m=gm_final,
        microstrip=microstrip, L=L_final, f_min=f_min, f_geom=f_geom,
    )
    assembly_final = TaperAssembly(
        settings, profile_final, microstrip, left_chain, right_chain,
    )
    result_final = assembly_final.evaluate()

    return OptimizerResult(
        L_opt=L_final,
        left_trim_opt=best_params.get("left_trim", 0.0),
        right_trim_opt=best_params.get("right_trim", 0.0),
        Gamma_m_opt=gm_final,
        objective_initial=obj_initial,
        objective_final=powell_result.fun,
        s11_max_initial_db=s11_initial,
        s11_max_final_db=float(np.max(result_final.s11_db)),
        assembly_result=result_final,
        n_evals=eval_count[0],
        converged=powell_result.success,
    )
