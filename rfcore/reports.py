"""Engineering report generation for taper assembly results.

Produces structured reports for engineering review:
  - Predicted S11/S21 over frequency
  - Confidence / warning summary
  - Model assumptions used
  - Block-by-block breakdown of the assembled chain
  - Profile summary (impedance, widths, taper length)

Output formats:
  - Plain-text (terminal / log)
  - JSON (machine-readable, sidecar storage)
"""

from __future__ import annotations

import json
import datetime
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import numpy as np

from rfcore.config import RFProjectSettings
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import TaperAssembly, AssemblyResult
from rfcore.taper_body import TaperSegment
from rfcore.discontinuities.base import DiscontinuityBlock
from rfcore.warnings import WarningCollector, Severity


# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------

@dataclass
class FrequencyData:
    """S-parameter data at a single frequency point."""
    f_hz: float
    s11_mag: float
    s11_db: float
    s11_phase_deg: float
    s21_mag: float
    s21_db: float
    s21_phase_deg: float


@dataclass
class ProfileSummary:
    """Summary of the Klopfenstein taper profile."""
    ZS_ohm: float
    ZL_ohm: float
    Z_mid_ohm: float
    Gamma_m: float
    A_parameter: float
    rho_0: float
    L_m: float           # L_actual
    L_mm: float          # L_actual in mm
    L_min_m: float       # minimum theoretical length
    L_min_mm: float      # minimum theoretical length in mm
    length_margin: float # L_actual / L_min
    # Ideal electrical profile (includes endpoint steps)
    w_start_mm: float
    w_end_mm: float
    w_min_mm: float
    w_max_mm: float
    Z_raw_start: float
    Z_raw_end: float
    endpoint_step_ln: float    # = Γm in log-impedance
    # Layout-realized profile (endpoints clamped to feed widths)
    w_layout_start_mm: float
    w_layout_end_mm: float
    n_profile_samples: int


@dataclass
class BlockSummary:
    """Summary of one discontinuity block in the chain."""
    position: str          # "left" or "right"
    index: int
    name: str
    params: Dict[str, Any]
    warnings: List[str]


@dataclass
class ModelAssumptions:
    """All model assumptions used in the analysis."""
    microstrip_model: str
    dispersion_model: str
    conductor_loss_model: str
    dielectric_loss_model: str
    roughness_model: str
    zc_treatment: str
    loss_mechanism: str
    cascade_method: str
    segmentation_method: str
    width_inversion_method: str
    klopfenstein_variant: str
    f_geometry_ref_hz: float
    tand_treatment: str


@dataclass
class SegmentationSummary:
    """Summary of the adaptive segmentation."""
    n_segments: int
    dz_min_um: float
    dz_max_um: float
    dz_mean_um: float
    max_det_error: float
    used_fallback: bool


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

class TaperReport:
    """Structured engineering report for a taper assembly evaluation."""

    def __init__(
        self,
        settings: RFProjectSettings,
        profile: KlopfensteinProfile,
        assembly_result: AssemblyResult,
        left_chain: Optional[List[DiscontinuityBlock]] = None,
        right_chain: Optional[List[DiscontinuityBlock]] = None,
    ) -> None:
        self.settings = settings
        self.profile = profile
        self.result = assembly_result
        self.left_chain = left_chain or []
        self.right_chain = right_chain or []
        self._timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    # -----------------------------------------------------------------------
    # Data extraction
    # -----------------------------------------------------------------------

    def _frequency_data(self) -> List[FrequencyData]:
        """Extract per-frequency S-parameter data."""
        data = []
        for i, f in enumerate(self.result.freqs):
            s11 = self.result.s_params[i, 0, 0]
            s21 = self.result.s_params[i, 1, 0]
            data.append(FrequencyData(
                f_hz=float(f),
                s11_mag=float(abs(s11)),
                s11_db=float(self.result.s11_db[i]),
                s11_phase_deg=float(np.degrees(np.angle(s11))),
                s21_mag=float(abs(s21)),
                s21_db=float(self.result.s21_db[i]),
                s21_phase_deg=float(np.degrees(np.angle(s21))),
            ))
        return data

    def _profile_summary(self) -> ProfileSummary:
        import math
        p = self.profile
        return ProfileSummary(
            ZS_ohm=p.ZS,
            ZL_ohm=p.ZL,
            Z_mid_ohm=math.sqrt(p.ZS * p.ZL),
            Gamma_m=p.Gamma_m,
            A_parameter=p.A,
            rho_0=p.rho_0,
            L_m=p.L,
            L_mm=p.L * 1e3,
            L_min_m=p.L_min,
            L_min_mm=p.L_min * 1e3,
            length_margin=p.length_margin,
            w_start_mm=float(p.w_profile[0] * 1e3),
            w_end_mm=float(p.w_profile[-1] * 1e3),
            w_min_mm=float(np.min(p.w_profile) * 1e3),
            w_max_mm=float(np.max(p.w_profile) * 1e3),
            Z_raw_start=p.Z_raw_start,
            Z_raw_end=p.Z_raw_end,
            endpoint_step_ln=p.endpoint_step_ln,
            w_layout_start_mm=float(p.w_layout[0] * 1e3),
            w_layout_end_mm=float(p.w_layout[-1] * 1e3),
            n_profile_samples=p.n_samples,
        )

    def _block_summaries(self) -> List[BlockSummary]:
        blocks = []
        for i, b in enumerate(self.left_chain):
            blocks.append(BlockSummary(
                position="left", index=i, name=b.name,
                params=b.params(), warnings=b.validate(),
            ))
        for i, b in enumerate(self.right_chain):
            blocks.append(BlockSummary(
                position="right", index=i, name=b.name,
                params=b.params(), warnings=b.validate(),
            ))
        return blocks

    def _model_assumptions(self) -> ModelAssumptions:
        return ModelAssumptions(
            microstrip_model="Hammerstad-Jensen 1980 (quasi-static, thickness-corrected)",
            dispersion_model="Kirschning-Jansen 1982/1984 (P1-P4 for eeff, R1-R17 for Zc)",
            conductor_loss_model="Hammerstad CAD-grade (geometry-dependent edge current, W/h branches)",
            dielectric_loss_model="Pozar standard (k0*er*(eeff-1)*tand / (2*sqrt(eeff)*(er-1)))",
            roughness_model="Hammerstad K_sr = 1 + (2/pi)*atan(1.4*(delta/skin_depth)^2)"
                if self.settings.stackup.surface_roughness_m > 0
                else "Disabled (roughness = 0)",
            zc_treatment="Real-valued (loss enters only through complex gamma)",
            loss_mechanism="Complex propagation constant gamma = alpha + j*beta",
            cascade_method="ABCD multiplication with determinant conditioning check; "
                           "T-matrix fallback if |det-1| > 1e-3",
            segmentation_method="Adaptive dual-criterion (5 deg electrical length at f_stop, "
                                "2% fractional impedance change); max 2000 segments",
            width_inversion_method="Brent's method, bracket [10um, 50*h]",
            klopfenstein_variant="Classical Klopfenstein 1956 with Kajfez 1973 correction; "
                                 "25-term phi recursion",
            f_geometry_ref_hz=self.settings.analysis.f_geom,
            tand_treatment="Frequency-flat (v1); value from settings.stackup.df_10ghz",
        )

    def _segmentation_summary(self) -> SegmentationSummary:
        segs = self.result.body_segments
        if not segs:
            return SegmentationSummary(0, 0, 0, 0, 0, False)

        dzs = [s.dz for s in segs]
        return SegmentationSummary(
            n_segments=len(segs),
            dz_min_um=min(dzs) * 1e6,
            dz_max_um=max(dzs) * 1e6,
            dz_mean_um=(sum(dzs) / len(dzs)) * 1e6,
            max_det_error=max(self.result.det_errors) if self.result.det_errors else 0.0,
            used_fallback=any(self.result.used_fallbacks),
        )

    # -----------------------------------------------------------------------
    # Text report
    # -----------------------------------------------------------------------

    def to_text(self) -> str:
        """Generate plain-text engineering report."""
        lines: List[str] = []
        W = 72  # line width

        lines.append("=" * W)
        lines.append("KLOPFENSTEIN MICROSTRIP TAPER — ENGINEERING REPORT")
        lines.append("=" * W)
        lines.append(f"Generated: {self._timestamp}")
        lines.append("")

        # --- Confidence ---
        w = self.result.warnings
        if w.is_low_confidence:
            lines.append("*** WARNING: LOW CONFIDENCE — EM VALIDATION RECOMMENDED ***")
            lines.append("")

        # --- Profile ---
        ps = self._profile_summary()
        lines.append("-" * W)
        lines.append("TAPER PROFILE")
        lines.append("-" * W)
        lines.append(f"  ZS = {ps.ZS_ohm:.2f} Ω    ZL = {ps.ZL_ohm:.2f} Ω    "
                      f"Z_mid = {ps.Z_mid_ohm:.2f} Ω")
        lines.append(f"  Γ_m = {ps.Gamma_m:.4f}    A = {ps.A_parameter:.4f}    "
                      f"ρ₀ = {ps.rho_0:.4f}")
        lines.append("")
        lines.append("  Synthesis:")
        lines.append(f"    f_min (synthesis lower edge) = {self.profile.f_min/1e9:.3f} GHz")
        lines.append(f"    L_min = A/β(f_min) = {ps.L_min_mm:.3f} mm")
        if ps.length_margin != 1.0:
            lines.append(f"    length_margin = {ps.length_margin:.2f}")
        lines.append(f"    L_actual = {ps.L_mm:.3f} mm"
                      + (f"  ({ps.length_margin:.2f} × L_min)" if ps.length_margin != 1.0 else ""))
        lines.append("")
        lines.append("  Ideal electrical profile (raw Klopfenstein):")
        lines.append(f"    Z(0)  = {ps.Z_raw_start:.3f} Ω    Z(L)  = {ps.Z_raw_end:.3f} Ω")
        lines.append(f"    Width range: {ps.w_min_mm:.4f} – {ps.w_max_mm:.4f} mm")
        lines.append(f"    Endpoint step = ρ₀/cosh(A) = {ps.endpoint_step_ln:.6f} = Γm")
        lines.append(f"    (Inherent Klopfenstein design: endpoints carry Γm reflection)")
        lines.append("")
        lines.append("  Realized layout profile (endpoints clamped to feed widths):")
        lines.append(f"    w_start = {ps.w_layout_start_mm:.4f} mm (at ZS = {ps.ZS_ohm:.2f} Ω)")
        lines.append(f"    w_end   = {ps.w_layout_end_mm:.4f} mm (at ZL = {ps.ZL_ohm:.2f} Ω)")
        lines.append("")

        # --- Stackup ---
        s = self.settings.stackup
        lines.append("-" * W)
        lines.append("STACKUP")
        lines.append("-" * W)
        lines.append(f"  Laminate: {s.laminate}")
        lines.append(f"  Substrate height: {s.substrate_height_m*1e6:.1f} μm "
                      f"({s.substrate_height_m*1e3/0.0254:.1f} mil)")
        lines.append(f"  Copper thickness: {s.copper_thickness_m*1e6:.1f} μm")
        lines.append(f"  Dk (design): {s.dk_design:.3f}")
        lines.append(f"  Df (10 GHz): {s.df_10ghz:.4f}")
        lines.append(f"  Conductivity: {s.conductivity_s_per_m:.2e} S/m")
        lines.append(f"  Roughness: {s.surface_roughness_m*1e6:.2f} μm RMS")
        lines.append("")

        # --- Analysis settings ---
        a = self.settings.analysis
        lines.append("-" * W)
        lines.append("ANALYSIS SETTINGS")
        lines.append("-" * W)
        lines.append(f"  Analysis band: {a.f_start_hz/1e9:.3f} – {a.f_stop_hz/1e9:.3f} GHz "
                      f"({a.n_points} points)")
        lines.append(f"  Z_ref: {a.zref_ohm:.1f} Ω")
        lines.append(f"  f_geometry: {a.f_geom/1e9:.3f} GHz")
        lines.append(f"  Segmentation tolerance: {a.segmentation_tol:.2f}")
        lines.append(f"  Length margin: {a.length_margin:.2f}")
        lines.append("")

        # --- Segmentation ---
        ss = self._segmentation_summary()
        lines.append("-" * W)
        lines.append("SEGMENTATION")
        lines.append("-" * W)
        lines.append(f"  Segments: {ss.n_segments}")
        lines.append(f"  Δz range: {ss.dz_min_um:.1f} – {ss.dz_max_um:.1f} μm "
                      f"(mean {ss.dz_mean_um:.1f} μm)")
        lines.append(f"  Max det error: {ss.max_det_error:.2e}")
        lines.append(f"  T-matrix fallback used: {'Yes' if ss.used_fallback else 'No'}")
        lines.append("")

        # --- Block-by-block breakdown ---
        blocks = self._block_summaries()
        if blocks:
            lines.append("-" * W)
            lines.append("DISCONTINUITY BLOCKS")
            lines.append("-" * W)
            for b in blocks:
                lines.append(f"  [{b.position.upper()}][{b.index}] {b.name}")
                for k, v in b.params.items():
                    if k == "block":
                        continue
                    if isinstance(v, float):
                        lines.append(f"    {k}: {v:.6e}")
                    else:
                        lines.append(f"    {k}: {v}")
                if b.warnings:
                    for bw in b.warnings:
                        lines.append(f"    ⚠ {bw}")
            lines.append("")

        # --- Model assumptions ---
        ma = self._model_assumptions()
        lines.append("-" * W)
        lines.append("MODEL ASSUMPTIONS")
        lines.append("-" * W)
        lines.append(f"  Microstrip: {ma.microstrip_model}")
        lines.append(f"  Dispersion: {ma.dispersion_model}")
        lines.append(f"  Conductor loss: {ma.conductor_loss_model}")
        lines.append(f"  Dielectric loss: {ma.dielectric_loss_model}")
        lines.append(f"  Roughness: {ma.roughness_model}")
        lines.append(f"  Zc treatment: {ma.zc_treatment}")
        lines.append(f"  Loss mechanism: {ma.loss_mechanism}")
        lines.append(f"  Cascade: {ma.cascade_method}")
        lines.append(f"  Klopfenstein: {ma.klopfenstein_variant}")
        lines.append(f"  Width inversion: {ma.width_inversion_method}")
        lines.append(f"  tan δ: {ma.tand_treatment}")
        lines.append("")

        # --- S-parameter summary ---
        lines.append("-" * W)
        lines.append("S-PARAMETER SUMMARY")
        lines.append("-" * W)
        lines.append(f"  Max |S11|: {self.result.max_s11_db:.2f} dB")
        lines.append(f"  Worst insertion loss: {self.result.max_insertion_loss_db:.2f} dB")
        lines.append("")

        # --- S-parameter table (sampled) ---
        lines.append("-" * W)
        lines.append("S-PARAMETER DATA (sampled)")
        lines.append("-" * W)
        lines.append(f"  {'f (GHz)':>10s}  {'|S11| dB':>10s}  {'|S21| dB':>10s}  "
                      f"{'∠S11 (°)':>10s}  {'∠S21 (°)':>10s}")
        lines.append(f"  {'--------':>10s}  {'--------':>10s}  {'--------':>10s}  "
                      f"{'--------':>10s}  {'--------':>10s}")

        fd = self._frequency_data()
        # Sample ~20 points for readability
        n = len(fd)
        step = max(1, n // 20)
        for i in range(0, n, step):
            d = fd[i]
            lines.append(
                f"  {d.f_hz/1e9:10.3f}  {d.s11_db:10.2f}  {d.s21_db:10.2f}  "
                f"{d.s11_phase_deg:10.1f}  {d.s21_phase_deg:10.1f}"
            )
        # Always include last point
        if (n - 1) % step != 0:
            d = fd[-1]
            lines.append(
                f"  {d.f_hz/1e9:10.3f}  {d.s11_db:10.2f}  {d.s21_db:10.2f}  "
                f"{d.s11_phase_deg:10.1f}  {d.s21_phase_deg:10.1f}"
            )
        lines.append("")

        # --- Warnings ---
        if w.has_warnings:
            lines.append("-" * W)
            lines.append("WARNINGS")
            lines.append("-" * W)
            for warning in w.warnings:
                lines.append(f"  {warning}")
            lines.append("")

        lines.append("=" * W)
        lines.append("END OF REPORT")
        lines.append("=" * W)

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # JSON report
    # -----------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Generate machine-readable report as a dictionary."""
        fd = self._frequency_data()
        ps = self._profile_summary()
        ma = self._model_assumptions()
        ss = self._segmentation_summary()
        blocks = self._block_summaries()

        return {
            "report_version": "1.0",
            "timestamp": self._timestamp,
            "confidence": {
                "is_low_confidence": self.result.is_low_confidence,
                "n_warnings": len(self.result.warnings.warnings),
                "n_high": len(self.result.warnings.by_severity(Severity.HIGH)),
            },
            "profile": {
                "ZS_ohm": ps.ZS_ohm,
                "ZL_ohm": ps.ZL_ohm,
                "Z_mid_ohm": ps.Z_mid_ohm,
                "Gamma_m": ps.Gamma_m,
                "A": ps.A_parameter,
                "rho_0": ps.rho_0,
                "synthesis": {
                    "f_min_hz": self.profile.f_min,
                    "L_min_m": ps.L_min_m,
                    "length_margin": ps.length_margin,
                    "L_actual_m": ps.L_m,
                },
                "endpoint_steps": {
                    "description": "Inherent Klopfenstein endpoint steps of magnitude Gamma_m",
                    "step_magnitude_ln": ps.endpoint_step_ln,
                    "Z_raw_start_ohm": ps.Z_raw_start,
                    "Z_raw_end_ohm": ps.Z_raw_end,
                },
                "ideal_electrical": {
                    "w_start_m": float(self.profile.w_profile[0]),
                    "w_end_m": float(self.profile.w_profile[-1]),
                    "w_min_m": float(np.min(self.profile.w_profile)),
                    "w_max_m": float(np.max(self.profile.w_profile)),
                },
                "layout_realized": {
                    "description": "Endpoint widths clamped to feed-line widths for trace connectivity",
                    "w_start_m": float(self.profile.w_layout[0]),
                    "w_end_m": float(self.profile.w_layout[-1]),
                },
            },
            "stackup": self.settings.stackup.__dict__,
            "analysis": {
                "f_start_hz": self.settings.analysis.f_start_hz,
                "f_stop_hz": self.settings.analysis.f_stop_hz,
                "n_points": self.settings.analysis.n_points,
                "zref_ohm": self.settings.analysis.zref_ohm,
                "f_geometry_hz": self.settings.analysis.f_geom,
                "length_margin": self.settings.analysis.length_margin,
            },
            "segmentation": {
                "n_segments": ss.n_segments,
                "dz_min_m": ss.dz_min_um * 1e-6,
                "dz_max_m": ss.dz_max_um * 1e-6,
                "max_det_error": ss.max_det_error,
                "used_fallback": ss.used_fallback,
            },
            "blocks": [
                {
                    "position": b.position,
                    "index": b.index,
                    "name": b.name,
                    "params": b.params,
                    "warnings": b.warnings,
                }
                for b in blocks
            ],
            "model_assumptions": {
                "microstrip": ma.microstrip_model,
                "dispersion": ma.dispersion_model,
                "conductor_loss": ma.conductor_loss_model,
                "dielectric_loss": ma.dielectric_loss_model,
                "roughness": ma.roughness_model,
                "zc_treatment": ma.zc_treatment,
                "cascade": ma.cascade_method,
                "klopfenstein": ma.klopfenstein_variant,
                "tand": ma.tand_treatment,
            },
            "s_params_summary": {
                "max_s11_db": self.result.max_s11_db,
                "worst_insertion_loss_db": self.result.max_insertion_loss_db,
            },
            "s_params_data": [
                {
                    "f_hz": d.f_hz,
                    "s11_db": d.s11_db,
                    "s21_db": d.s21_db,
                    "s11_phase_deg": d.s11_phase_deg,
                    "s21_phase_deg": d.s21_phase_deg,
                }
                for d in fd
            ],
            "warnings": [str(w) for w in self.result.warnings.warnings],
        }

    def to_json(self, indent: int = 2) -> str:
        """Generate JSON report string."""
        return json.dumps(self.to_dict(), indent=indent)

    def save_text(self, path: str) -> None:
        """Save plain-text report to file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_text())

    def save_json(self, path: str) -> None:
        """Save JSON report to file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
