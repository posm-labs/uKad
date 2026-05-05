"""KiCad-native Klopfenstein taper footprint generator wizard.

wxPython dialog with:
  - Parameter panel (left): stackup, electrical, geometry, results
  - Live footprint preview (right, wx-native interactive canvas)
  - Toolbar: Synthesize, S-Params, Export, EM stub, Stackup, Save, Close

All RF math goes through rfcore (unchanged). This module is UI only.
Preview uses wx.GraphicsContext (no matplotlib).
S-param viewer uses Plotly HTML (no matplotlib).
"""

from __future__ import annotations
import hashlib
import logging
import pathlib
import time
import traceback
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import wx
    HAS_WX = True
except ImportError:
    HAS_WX = False

import numpy as np
from rfcore.config import RFProjectSettings
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import AssemblyResult


class TaperWizard(wx.Dialog):
    """Klopfenstein taper footprint generator wizard."""

    def __init__(self, parent, kicad_ver=(8, 0, 0)):
        super().__init__(parent, title="RF Klopfenstein Taper Generator",
                         size=(1050, 700),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._ver = kicad_ver
        self._profile: Optional[KlopfensteinProfile] = None
        self._result: Optional[AssemblyResult] = None
        self._settings = RFProjectSettings()
        self._last_lib_path: Optional[pathlib.Path] = None
        self._cache_key: Optional[str] = None  # RF result cache key
        self._build_ui()
        self.CenterOnParent()

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        main = wx.BoxSizer(wx.VERTICAL)

        # Toolbar
        tb = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_synth = wx.Button(self, label="Synthesize")
        self._btn_sparam = wx.Button(self, label="S-Parameters")
        self._btn_export = wx.Button(self, label="Export S-Params")
        self._btn_em = wx.Button(self, label="EM Simulation")
        self._btn_stackup = wx.Button(self, label="Stackup Settings")
        self._btn_save = wx.Button(self, label="Save Footprint")
        self._btn_close = wx.Button(self, id=wx.ID_CLOSE, label="Close")

        for b in [self._btn_synth, self._btn_sparam, self._btn_export,
                   self._btn_em, self._btn_stackup, self._btn_save, self._btn_close]:
            tb.Add(b, 0, wx.ALL, 3)

        self._btn_synth.Bind(wx.EVT_BUTTON, self._on_synthesize)
        self._btn_sparam.Bind(wx.EVT_BUTTON, self._on_sparams)
        self._btn_export.Bind(wx.EVT_BUTTON, self._on_export)
        self._btn_em.Bind(wx.EVT_BUTTON, self._on_em)
        self._btn_stackup.Bind(wx.EVT_BUTTON, self._on_stackup)
        self._btn_save.Bind(wx.EVT_BUTTON, self._on_save)
        self._btn_close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

        self._btn_sparam.Disable()
        self._btn_export.Disable()
        self._btn_save.Disable()

        main.Add(tb, 0, wx.EXPAND | wx.ALL, 4)

        # Main split: params (left) | preview (right)
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        left = self._build_params(splitter)
        right = self._build_preview(splitter)
        splitter.SplitVertically(left, right, 360)
        splitter.SetMinimumPaneSize(280)
        main.Add(splitter, 1, wx.EXPAND | wx.ALL, 4)

        self.SetSizer(main)

    def _build_params(self, parent):
        panel = wx.ScrolledWindow(parent)
        panel.SetScrollRate(0, 10)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Electrical target ──
        box_e = wx.StaticBoxSizer(wx.VERTICAL, panel, "Electrical Target")
        grid_e = wx.FlexGridSizer(cols=2, hgap=8, vgap=4)
        grid_e.AddGrowableCol(1)

        self._zs = self._add_field(grid_e, panel, "ZS (Ω):", "50.0")
        self._zl = self._add_field(grid_e, panel, "ZL (Ω):", "75.0")
        self._gm = self._add_field(grid_e, panel, "Γm:", "0.05")
        self._fstart = self._add_field(grid_e, panel, "f_start (GHz):", "1.0")
        self._fstop = self._add_field(grid_e, panel, "f_stop (GHz):", "10.0")
        self._lm = self._add_field(grid_e, panel, "Length multiplier:", "1.0")
        self._lm.SetToolTip("L_body = multiplier × L_min. Values >1 create a longer, more conservative taper.")

        box_e.Add(grid_e, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(box_e, 0, wx.EXPAND | wx.BOTTOM, 6)

        # ── Geometry ──
        box_g = wx.StaticBoxSizer(wx.VERTICAL, panel, "Geometry")
        grid_g = wx.FlexGridSizer(cols=2, hgap=8, vgap=4)
        grid_g.AddGrowableCol(1)

        self._land_s = self._add_field(grid_g, panel, "Input landing length (mm):", "0.5")
        self._land_s.SetToolTip("Constant-width routing section at input. Width = w_start.")
        self._land_e = self._add_field(grid_g, panel, "Output landing length (mm):", "0.5")
        self._land_e.SetToolTip("Constant-width routing section at output. Width = w_end.")
        self._fp_name = self._add_field(grid_g, panel, "Footprint name:", "")

        box_g.Add(grid_g, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(box_g, 0, wx.EXPAND | wx.BOTTOM, 6)

        # ── Results ──
        box_r = wx.StaticBoxSizer(wx.VERTICAL, panel, "Computed Results")
        self._results_text = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 220))
        self._results_text.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE,
                                           wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self._results_text.SetValue("Click 'Synthesize' to compute.")
        box_r.Add(self._results_text, 1, wx.EXPAND | wx.ALL, 4)
        sizer.Add(box_r, 1, wx.EXPAND)

        panel.SetSizer(sizer)
        return panel

    def _build_preview(self, parent):
        from addon.fp_canvas import FootprintCanvas
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._fp_canvas = FootprintCanvas(panel)
        sizer.Add(self._fp_canvas, 1, wx.EXPAND)

        # Fit view button
        btn_fit = wx.Button(panel, label="Fit View")
        btn_fit.Bind(wx.EVT_BUTTON, lambda e: self._fp_canvas.fit_view())
        sizer.Add(btn_fit, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        panel.SetSizer(sizer)
        return panel

    def _add_field(self, grid, panel, label, default):
        grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl = wx.TextCtrl(panel, value=default, size=(120, -1))
        grid.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    # ── Preview update ──────────────────────────────────────────────

    def _update_preview(self):
        """Update preview canvas with current geometry. No RF recomputation."""
        if self._profile is None:
            return
        from addon.footprint_gen import footprint_dimensions, _taper_polygon_mm
        spec = self._current_spec()
        poly = _taper_polygon_mm(spec)
        dims = footprint_dimensions(spec)
        self._fp_canvas.set_geometry(poly, dims)

    # ── Helpers ───────────────────────────────────────────────────────

    def _current_spec(self):
        from addon.footprint_gen import FootprintSpec, auto_footprint_name
        profile = self._profile

        ZS = float(self._zs.GetValue())
        ZL = float(self._zl.GetValue())
        Gamma_m = float(self._gm.GetValue())
        f_start = float(self._fstart.GetValue()) * 1e9
        f_stop = float(self._fstop.GetValue()) * 1e9

        name = self._fp_name.GetValue().strip()
        if not name:
            name = auto_footprint_name(ZS, ZL, Gamma_m, f_start)

        return FootprintSpec(
            profile=profile,
            fp_name=name,
            landing_start_m=float(self._land_s.GetValue()) * 1e-3,
            landing_end_m=float(self._land_e.GetValue()) * 1e-3,
            ZS=ZS, ZL=ZL, Gamma_m=Gamma_m,
            f_start_hz=f_start, f_stop_hz=f_stop,
        )

    def _safe_float(self, ctrl, default, label="value"):
        """Parse float from text control, show error and return default on failure."""
        try:
            v = float(ctrl.GetValue())
            return v
        except (ValueError, TypeError):
            wx.MessageBox(f"Invalid {label}: '{ctrl.GetValue()}'\nUsing default {default}.",
                          "Input Error", wx.OK | wx.ICON_WARNING)
            ctrl.SetValue(str(default))
            return default

    def _read_params(self):
        return {
            "ZS": self._safe_float(self._zs, 50.0, "ZS"),
            "ZL": self._safe_float(self._zl, 75.0, "ZL"),
            "Gamma_m": self._safe_float(self._gm, 0.05, "Γm"),
            "f_start": self._safe_float(self._fstart, 1.0, "f_start") * 1e9,
            "f_stop": self._safe_float(self._fstop, 10.0, "f_stop") * 1e9,
            "length_margin": self._safe_float(self._lm, 1.0, "Length multiplier"),
            "landing_start_m": self._safe_float(self._land_s, 0.5, "Input landing") * 1e-3,
            "landing_end_m": self._safe_float(self._land_e, 0.5, "Output landing") * 1e-3,
        }

    # ── RF result caching ──────────────────────────────────────────

    def _rf_cache_key(self, p: dict) -> str:
        """Build cache key from all RF-relevant parameters."""
        s = self._settings.stackup
        parts = [
            f"ZS={p['ZS']}", f"ZL={p['ZL']}", f"Gm={p['Gamma_m']}",
            f"fs={p['f_start']}", f"fe={p['f_stop']}", f"lm={p['length_margin']}",
            f"h={s.substrate_height_m}", f"dk={s.dk_design}",
            f"df={s.df_10ghz}", f"tcu={s.copper_thickness_m}",
            f"rq={s.surface_roughness_m}", f"sig={s.conductivity_s_per_m}",
            f"nf={self._settings.analysis.n_points}",
            f"ls={p.get('landing_start_m', 0)}",
            f"le={p.get('landing_end_m', 0)}",
        ]
        return hashlib.md5("|".join(parts).encode()).hexdigest()

    # ── Button handlers ──────────────────────────────────────────────

    def _on_synthesize(self, event):
        logger.info("Synthesize clicked")
        try:
            t0 = time.perf_counter()
            p = self._read_params()

            # Check cache
            key = self._rf_cache_key(p)
            if key == self._cache_key and self._result is not None:
                logger.info("RF cache hit — skipping synthesis")
            else:
                from addon.ui_main import synthesize_taper_with_landings, SynthesisRequest

                self._settings.analysis.f_start_hz = p["f_start"]
                self._settings.analysis.f_stop_hz = p["f_stop"]
                self._settings.analysis.length_margin = p["length_margin"]

                request = SynthesisRequest(
                    ZS_ohm=p["ZS"], ZL_ohm=p["ZL"], Gamma_m=p["Gamma_m"])
                result, report, profile = synthesize_taper_with_landings(
                    request, self._settings,
                    landing_start_m=p["landing_start_m"],
                    landing_end_m=p["landing_end_m"],
                )

                self._profile = profile
                self._result = result
                self._cache_key = key
                logger.info("Synthesis OK: L=%.3f mm (%.1f ms)",
                            profile.L * 1e3, (time.perf_counter() - t0) * 1000)

            result = self._result
            profile = self._profile
            from addon.footprint_gen import footprint_dimensions
            spec = self._current_spec()
            dims = footprint_dimensions(spec)

            lines = [
                f"ZS = {p['ZS']:.1f} Ω   (z01 = {result.z01:.1f} Ω)",
                f"ZL = {p['ZL']:.1f} Ω   (z02 = {result.z02:.1f} Ω)",
                f"Γm = {p['Gamma_m']:.4f}",
                f"f_start = {p['f_start']/1e9:.2f} GHz",
                f"f_stop = {p['f_stop']/1e9:.2f} GHz",
                "",
                f"L_min   = {profile.L_min*1e3:.3f} mm",
                f"L_mult  = {p['length_margin']:.2f}x",
                f"L_body  = {dims['L_body_mm']:.3f} mm  (RF taper)",
                f"L_land_in  = {dims['L_landing_start_mm']:.3f} mm",
                f"L_land_out = {dims['L_landing_end_mm']:.3f} mm",
                f"L_total = {dims['L_total_mm']:.3f} mm",
                "",
                f"w_start = {dims['w_start_mm']:.4f} mm",
                f"w_end   = {dims['w_end_mm']:.4f} mm",
                "",
                f"Max |S11| = {result.max_s11_db:.1f} dB",
                f"Max |S22| = {result.max_s22_db:.1f} dB",
                f"Worst IL  = {result.max_insertion_loss_db:.2f} dB",
                "",
                f"Source: Fast analytical model",
                f"Compute: {(time.perf_counter() - t0) * 1000:.0f} ms",
            ]
            self._results_text.SetValue("\n".join(lines))
            self._update_preview()

            if not self._fp_name.GetValue().strip():
                from addon.footprint_gen import auto_footprint_name
                self._fp_name.SetValue(
                    auto_footprint_name(p["ZS"], p["ZL"], p["Gamma_m"], p["f_start"]))

            self._btn_sparam.Enable()
            self._btn_export.Enable()
            self._btn_save.Enable()

        except Exception as e:
            logger.error("Synthesis failed: %s\n%s", e, traceback.format_exc())
            wx.MessageBox(f"Synthesis failed:\n{e}", "Error",
                          wx.OK | wx.ICON_ERROR)

    def _on_sparams(self, event):
        logger.info("S-Parameters clicked")
        if self._result is None:
            wx.MessageBox("Please synthesize first.", "S-Parameters",
                          wx.OK | wx.ICON_INFORMATION)
            return
        try:
            from addon.sparam_view import show_sparams
            show_sparams(self._result, self._read_params(), parent=self)
            logger.info("S-Parameter viewer closed")
        except Exception as e:
            logger.error("S-param viewer failed: %s\n%s", e, traceback.format_exc())
            wx.MessageBox(f"S-parameter viewer failed:\n{e}", "Error",
                          wx.OK | wx.ICON_ERROR)

    def _on_export(self, event):
        if self._result is None or self._profile is None:
            return
        choices = ["Touchstone 2.0 (.ts)", "Touchstone 1.0 (.s2p)", "CSV (.csv)"]
        dlg = wx.SingleChoiceDialog(self, "Export format:", "Export S-Parameters", choices)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        choice = dlg.GetSelection()
        dlg.Destroy()

        wildcard = ["Touchstone 2.0 (*.ts)|*.ts",
                     "Touchstone 1.0 (*.s2p)|*.s2p",
                     "CSV (*.csv)|*.csv"][choice]
        fd = wx.FileDialog(self, "Save S-Parameters", wildcard=wildcard,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if fd.ShowModal() != wx.ID_OK:
            fd.Destroy()
            return
        path = fd.GetPath()
        fd.Destroy()

        try:
            logger.info("Export choice=%d path=%s", choice, path)
            if choice == 0:
                from rfcore.export.touchstone import export_touchstone_v2
                export_touchstone_v2(self._result, path)
            elif choice == 1:
                from rfcore.export.touchstone import export_touchstone_v1
                export_touchstone_v1(self._result, path)
            else:
                from rfcore.export.csv_export import export_frequency_csv
                export_frequency_csv(self._result, path)
            wx.MessageBox(f"Saved: {path}", "Export Complete", wx.OK | wx.ICON_INFORMATION)
            logger.info("Export saved: %s", path)
        except Exception as e:
            logger.error("Export failed: %s\n%s", e, traceback.format_exc())
            wx.MessageBox(f"Export failed:\n{e}\n\n{traceback.format_exc()}",
                          "Error", wx.OK | wx.ICON_ERROR)

    def _on_em(self, event):
        logger.info("EM Simulation clicked (stub)")
        wx.MessageBox(
            "EM simulation backend is not implemented yet.\n\n"
            "Future versions will integrate with openEMS for\n"
            "full-wave verification of the taper design.\n\n"
            "Current results use the fast analytical model.",
            "EM Simulation", wx.OK | wx.ICON_INFORMATION)

    def _on_stackup(self, event):
        logger.info("Stackup Settings clicked")
        dlg = StackupDialog(self, self._settings)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_save(self, event):
        logger.info("Save Footprint clicked")
        if self._profile is None:
            wx.MessageBox("Please synthesize first.", "Save",
                          wx.OK | wx.ICON_INFORMATION)
            return
        from addon.footprint_gen import (
            generate_footprint, save_footprint, default_library_path,
            library_registration_instructions)

        spec = self._current_spec()
        content = generate_footprint(spec)

        lib_path = self._last_lib_path or default_library_path()
        dd = wx.DirDialog(self, "Choose footprint library (.pretty) directory",
                          str(lib_path.parent),
                          style=wx.DD_DEFAULT_STYLE)
        if dd.ShowModal() != wx.ID_OK:
            dd.Destroy()
            return
        chosen = pathlib.Path(dd.GetPath())
        dd.Destroy()

        if not chosen.name.endswith(".pretty"):
            chosen = chosen / "Klopfenstein_Tapers.pretty"
        self._last_lib_path = chosen

        try:
            fp_path = save_footprint(content, spec.fp_name, chosen)
            logger.info("Footprint saved: %s", fp_path)
            instructions = library_registration_instructions(chosen)
            wx.MessageBox(
                f"Footprint saved:\n{fp_path}\n\n{instructions}",
                "Save Complete", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            logger.error("Save failed: %s\n%s", e, traceback.format_exc())
            wx.MessageBox(f"Save failed:\n{e}", "Error", wx.OK | wx.ICON_ERROR)



# ── Stackup Settings Dialog ──────────────────────────────────────────

class StackupDialog(wx.Dialog):
    """Display/edit stackup parameters (read-only in v1)."""

    def __init__(self, parent, settings: RFProjectSettings):
        super().__init__(parent, title="Stackup Settings", size=(400, 380))
        sizer = wx.BoxSizer(wx.VERTICAL)

        s = settings.stackup
        box = wx.StaticBoxSizer(wx.VERTICAL, self, f"{s.laminate} ({s.substrate_height_m*1e3:.1f} mil)")
        grid = wx.FlexGridSizer(cols=2, hgap=12, vgap=6)
        grid.AddGrowableCol(1)

        fields = [
            ("Laminate:", s.laminate),
            ("Substrate height:", f"{s.substrate_height_m*1e6:.1f} um ({s.substrate_height_m*1e3/0.0254:.1f} mil)"),
            ("Dk (design):", f"{s.dk_design:.2f}"),
            ("Df (tan d):", f"{s.df_10ghz:.4f}"),
            ("Cu thickness:", f"{s.copper_thickness_m*1e6:.1f} um"),
            ("Cu roughness (Rq):", f"{s.surface_roughness_m*1e6:.2f} um"),
            ("Cu conductivity:", f"{s.conductivity_s_per_m:.1e} S/m"),
            ("Soldermask:", "Present" if s.soldermask_present else "Not modeled (v1)"),
        ]
        for label, value in fields:
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(wx.StaticText(self, label=value), 0, wx.ALIGN_CENTER_VERTICAL)

        box.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(box, 1, wx.EXPAND | wx.ALL, 10)

        note = wx.StaticText(self,
            label="Editable / multiple stackups planned for future version.\n"
                  f"Currently using {s.laminate} defaults.")
        note.SetForegroundColour(wx.Colour(120, 120, 120))
        sizer.Add(note, 0, wx.ALL, 10)

        btn = wx.Button(self, wx.ID_OK, "OK")
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        self.SetSizer(sizer)
        self.CenterOnParent()


# For backward compatibility / standalone testing
TaperDialog = TaperWizard
