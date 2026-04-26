"""Main addon entry point — orchestrates taper synthesis workflow.

This is the top-level module that ties rfcore and KiCad together.
It provides the complete workflow:

  1. Load/create settings from sidecar JSON
  2. (Optional) Extract endpoint geometry from the board
  3. Synthesize the Klopfenstein profile
  4. Build the discontinuity chain from extracted geometry
  5. Evaluate the assembly (fast model)
  6. Generate engineering report
  7. (Optional) Insert taper tracks into the board
  8. Save settings and report as sidecar files

No RF modeling code lives here.  This module only calls into rfcore.
"""

from __future__ import annotations

import pathlib
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import TaperAssembly, AssemblyResult
from rfcore.reports import TaperReport
from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.discontinuities.step import WidthStepBlock
from rfcore.discontinuities.pad import PadBlock
from rfcore.discontinuities.via_signal import SignalViaSelfBlock
from rfcore.discontinuities.stub import StubBlock
from rfcore.discontinuities.return_path import ReturnPathBlock

logger = logging.getLogger(__name__)


@dataclass
class SynthesisRequest:
    """User request for a taper synthesis."""

    # Taper endpoints
    ZS_ohm: float = 50.0
    ZL_ohm: float = 75.0
    Gamma_m: float = 0.05

    # Placement (board coordinates, metres)
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0
    angle_deg: float = 0.0
    layer: str = "F.Cu"
    net_name: str = ""

    # Optional fixed length (None = auto from f_min)
    L_fixed_m: Optional[float] = None

    # Endpoint geometry (if known; otherwise extracted from board)
    w_start_m: Optional[float] = None
    w_end_m: Optional[float] = None


def synthesize_taper(
    request: SynthesisRequest,
    settings: Optional[RFProjectSettings] = None,
) -> Tuple[AssemblyResult, TaperReport, KlopfensteinProfile]:
    """Synthesize a Klopfenstein taper and produce an engineering report.

    This is the main entry point for non-interactive (headless) use.
    It does not require a KiCad connection.

    Parameters
    ----------
    request : SynthesisRequest
        Taper specification.
    settings : RFProjectSettings or None
        Project settings.  Uses defaults if None.

    Returns
    -------
    (assembly_result, report, profile) : tuple
    """
    if settings is None:
        settings = RFProjectSettings()

    # Build microstrip model
    microstrip = MicrostripModel.from_settings(settings)

    # Build Klopfenstein profile
    profile = KlopfensteinProfile(
        ZS=request.ZS_ohm,
        ZL=request.ZL_ohm,
        Gamma_m=request.Gamma_m,
        microstrip=microstrip,
        L=request.L_fixed_m,
        f_min=settings.analysis.f_start_hz,
        f_geom=settings.analysis.f_geom,
        length_margin=settings.analysis.length_margin,
    )

    # Build discontinuity chains (empty for headless mode without board data)
    left_chain: List[DiscontinuityBlock] = []
    right_chain: List[DiscontinuityBlock] = []

    # Evaluate assembly
    assembly = TaperAssembly(
        settings, profile, microstrip, left_chain, right_chain,
    )
    result = assembly.evaluate()

    # Generate report
    report = TaperReport(
        settings, profile, result, left_chain, right_chain,
    )

    return result, report, profile


def synthesize_with_discontinuities(
    request: SynthesisRequest,
    settings: RFProjectSettings,
    left_blocks: Optional[List[DiscontinuityBlock]] = None,
    right_blocks: Optional[List[DiscontinuityBlock]] = None,
) -> Tuple[AssemblyResult, TaperReport, KlopfensteinProfile]:
    """Synthesize with explicit discontinuity blocks.

    Use this when endpoint geometry is known (from board extraction
    or manual specification).

    Parameters
    ----------
    request : SynthesisRequest
    settings : RFProjectSettings
    left_blocks : list of DiscontinuityBlock
    right_blocks : list of DiscontinuityBlock

    Returns
    -------
    (assembly_result, report, profile) : tuple
    """
    microstrip = MicrostripModel.from_settings(settings)

    profile = KlopfensteinProfile(
        ZS=request.ZS_ohm,
        ZL=request.ZL_ohm,
        Gamma_m=request.Gamma_m,
        microstrip=microstrip,
        L=request.L_fixed_m,
        f_min=settings.analysis.f_start_hz,
        f_geom=settings.analysis.f_geom,
        length_margin=settings.analysis.length_margin,
    )

    left_chain = left_blocks or []
    right_chain = right_blocks or []

    assembly = TaperAssembly(
        settings, profile, microstrip, left_chain, right_chain,
    )
    result = assembly.evaluate()

    report = TaperReport(
        settings, profile, result, left_chain, right_chain,
    )

    return result, report, profile


# ---------------------------------------------------------------------------
# Sidecar file management
# ---------------------------------------------------------------------------

def sidecar_path(board_path: str, suffix: str = ".kicad_rf.json") -> pathlib.Path:
    """Compute the sidecar file path for a given board file.

    Example: /path/to/board.kicad_pcb → /path/to/board.kicad_rf.json
    """
    p = pathlib.Path(board_path)
    return p.with_suffix(suffix)


def load_or_create_settings(board_path: str) -> RFProjectSettings:
    """Load settings from sidecar file, or create defaults."""
    sp = sidecar_path(board_path)
    if sp.exists():
        logger.info(f"Loading settings from {sp}")
        return RFProjectSettings.load(sp)
    else:
        logger.info(f"No sidecar found at {sp}, using defaults")
        return RFProjectSettings()


def save_settings(board_path: str, settings: RFProjectSettings) -> pathlib.Path:
    """Save settings to sidecar file."""
    sp = sidecar_path(board_path)
    settings.save(sp)
    logger.info(f"Settings saved to {sp}")
    return sp


def save_report(
    board_path: str,
    report: TaperReport,
    text: bool = True,
    json_out: bool = True,
) -> List[pathlib.Path]:
    """Save report files alongside the board.

    Produces:
      <board>.kicad_rf_report.txt  (if text=True)
      <board>.kicad_rf_report.json (if json_out=True)

    Returns list of saved file paths.
    """
    saved: List[pathlib.Path] = []
    base = pathlib.Path(board_path)

    if text:
        tp = base.with_suffix(".kicad_rf_report.txt")
        report.save_text(str(tp))
        saved.append(tp)
        logger.info(f"Text report saved to {tp}")

    if json_out:
        jp = base.with_suffix(".kicad_rf_report.json")
        report.save_json(str(jp))
        saved.append(jp)
        logger.info(f"JSON report saved to {jp}")

    return saved
