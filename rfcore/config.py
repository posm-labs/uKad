"""Project-level RF settings model and board-level persistence.

RFProjectSettings is the single shared configuration object read by every
rfcore module.  It is stored as a sidecar JSON file next to the .kicad_pcb
board file (<boardname>.kicad_rf.json).

All values are SI units internally:
  lengths  → metres (m)
  freq     → hertz (Hz)
  conductivity → siemens/metre (S/m)
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Stackup configuration
# ---------------------------------------------------------------------------

@dataclass
class StackupSettings:
    """Physical stackup parameters for a single microstrip layer."""

    line_type: str = "microstrip"
    laminate: str = "RO4350B"
    substrate_height_m: float = 0.254e-3          # 10 mil default
    copper_thickness_m: float = 35.0e-6            # 1 oz Cu
    surface_roughness_m: float = 0.5e-6            # RMS roughness
    dk_design: float = 3.48                        # process Dk @ 10 GHz
    df_10ghz: float = 0.0037                       # loss tangent @ 10 GHz
    conductivity_s_per_m: float = 5.8e7            # annealed Cu
    ground_plane_continuous: bool = True
    soldermask_present: bool = False

    def validate(self) -> list[str]:
        """Return list of validation error strings (empty = valid)."""
        errors: list[str] = []
        if self.line_type != "microstrip":
            errors.append(
                f"Unsupported line_type '{self.line_type}'; v1 supports 'microstrip' only."
            )
        if self.substrate_height_m <= 0:
            errors.append("substrate_height_m must be positive.")
        if self.copper_thickness_m < 0:
            errors.append("copper_thickness_m must be non-negative.")
        if self.surface_roughness_m < 0:
            errors.append("surface_roughness_m must be non-negative.")
        if self.dk_design <= 1.0:
            errors.append("dk_design must be > 1.0 for a dielectric substrate.")
        if not (0.0 <= self.df_10ghz <= 0.5):
            errors.append("df_10ghz must be in [0, 0.5].")
        if self.conductivity_s_per_m <= 0:
            errors.append("conductivity_s_per_m must be positive.")
        if not self.ground_plane_continuous:
            errors.append(
                "v1 requires ground_plane_continuous = true.  "
                "Non-continuous ground planes are not modeled."
            )
        return errors


# ---------------------------------------------------------------------------
# Analysis configuration
# ---------------------------------------------------------------------------

@dataclass
class AnalysisSettings:
    """Frequency sweep and segmentation parameters."""

    zref_ohm: float = 50.0
    f_start_hz: float = 1.0e9                      # 1 GHz default
    f_stop_hz: float = 20.0e9                      # 20 GHz default
    n_points: int = 201
    f_geometry_ref_hz: Optional[float] = None       # None → use f_start_hz (= f_min)
    segmentation_tol: float = 1.0                   # 1.0 = default refinement thresholds
    length_margin: float = 1.0                        # L = length_margin * L_min; range [1.0, 4.0]
    warn_if_electrically_short: bool = True

    @property
    def f_geom(self) -> float:
        """Geometry-synthesis frequency.  Defaults to f_start_hz."""
        return self.f_geometry_ref_hz if self.f_geometry_ref_hz is not None else self.f_start_hz

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.zref_ohm <= 0:
            errors.append("zref_ohm must be positive.")
        if self.f_start_hz <= 0:
            errors.append("f_start_hz must be positive.")
        if self.f_stop_hz <= self.f_start_hz:
            errors.append("f_stop_hz must be > f_start_hz.")
        if self.n_points < 2:
            errors.append("n_points must be >= 2.")
        if self.segmentation_tol <= 0:
            errors.append("segmentation_tol must be positive.")
        if not (1.0 <= self.length_margin <= 4.0):
            errors.append("length_margin must be in [1.0, 4.0].")
        if self.f_geometry_ref_hz is not None and self.f_geometry_ref_hz <= 0:
            errors.append("f_geometry_ref_hz must be positive when set.")
        return errors


# ---------------------------------------------------------------------------
# Discontinuity enable/disable flags
# ---------------------------------------------------------------------------

@dataclass
class DiscontinuitySettings:
    """Controls which endpoint discontinuity blocks are active."""

    enable_step_model: bool = True
    enable_pad_model: bool = True
    enable_ground_via_model: bool = True
    enable_signal_via_model: bool = True
    enable_stub_model: bool = True
    enable_return_path_model: bool = True


# ---------------------------------------------------------------------------
# EM backend configuration
# ---------------------------------------------------------------------------

@dataclass
class EMSettings:
    """Configuration for optional EM solver path."""

    backend: str = "openems"
    capture_margin_m: float = 2.0e-3               # 2 mm
    port_extension_m: float = 1.0e-3               # 1 mm
    mesh_density_hint: float = 1.0                  # 1.0 = default
    max_em_evals: int = 12


# ---------------------------------------------------------------------------
# Top-level project settings
# ---------------------------------------------------------------------------

@dataclass
class RFProjectSettings:
    """Complete RF project configuration.

    One instance per board / project.  Shared by every RF tool invocation.
    Persisted as ``<boardname>.kicad_rf.json``.
    """

    stackup: StackupSettings = field(default_factory=StackupSettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    discontinuities: DiscontinuitySettings = field(default_factory=DiscontinuitySettings)
    em: EMSettings = field(default_factory=EMSettings)

    # ----- validation -----

    def validate(self) -> list[str]:
        """Validate all sub-settings.  Returns list of error strings."""
        errors: list[str] = []
        errors.extend(self.stackup.validate())
        errors.extend(self.analysis.validate())
        return errors

    # ----- persistence -----

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> "RFProjectSettings":
        return cls(
            stackup=StackupSettings(**d.get("stackup", {})),
            analysis=AnalysisSettings(**d.get("analysis", {})),
            discontinuities=DiscontinuitySettings(**d.get("discontinuities", {})),
            em=EMSettings(**d.get("em", {})),
        )

    @classmethod
    def from_json(cls, text: str) -> "RFProjectSettings":
        return cls.from_dict(json.loads(text))

    def save(self, path: pathlib.Path) -> None:
        """Write settings to a JSON sidecar file."""
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path) -> "RFProjectSettings":
        """Load settings from a JSON sidecar file."""
        text = path.read_text(encoding="utf-8")
        return cls.from_json(text)
