"""KiCad-native Klopfenstein taper footprint generator wizard.

wxPython dialog with:
  - Parameter panel (left): stackup, electrical, geometry, results
  - Live footprint preview (right, KiCad-like dark canvas)
  - Toolbar: Synthesize, S-Params, Export, EM stub, Stackup, Save, Close

All RF math goes through rfcore (unchanged). This module is UI only.
"""

from __future__ import annotations
import logging
import pathlib
import traceback
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import wx
    HAS_WX = True
except ImportError:
    HAS_WX = False

try:
    import matplotlib
    matplotlib.use("WXAgg")
    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

import numpy as np
from rfcore.config import RFProjectSettings
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import AssemblyResult

_C_S11 = "#1f77b4"
_C_S21 = "#2ca02c"
_C_S22 = "#d62728"
_C_TARGET = "#888888"
# KiCad-like preview colors
_C_BG = "#1a1a2e"       # dark canvas background
_C_GRID = "#2a2a4a"     # subtle grid
_C_COPPER = "#cc3333"   # F.Cu red
_C_PAD_FILL = "#cc3333" # pad fill (same copper)
_C_ORIGIN = "#cccccc"   # crosshair
_C_DIM = "#6688cc"      # dimension annotations


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
        self._lm = self._add_field(grid_e, panel, "length_margin:", "1.0")

        box_e.Add(grid_e, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(box_e, 0, wx.EXPAND | wx.BOTTOM, 6)

        # ── Geometry ──
        box_g = wx.StaticBoxSizer(wx.VERTICAL, panel, "Geometry")
        grid_g = wx.FlexGridSizer(cols=2, hgap=8, vgap=4)
        grid_g.AddGrowableCol(1)

        self._land_s = self._add_field(grid_g, panel, "Input landing (mm):", "0.5")
        self._land_e = self._add_field(grid_g, panel, "Output landing (mm):", "0.5")
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
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        if HAS_MPL:
            self._fig = Figure(figsize=(5, 4), dpi=100)
            self._fig.patch.set_facecolor(_C_BG)
            self._ax_prev = self._fig.add_subplot(111)
            self._canvas = FigureCanvas(panel, -1, self._fig)
            sizer.Add(self._canvas, 1, wx.EXPAND)
            self._draw_empty_preview()
        else:
            lbl = wx.StaticText(panel, label="matplotlib not available.\nPreview disabled.")
            sizer.Add(lbl, 1, wx.EXPAND | wx.ALL, 20)

        panel.SetSizer(sizer)
        return panel

    def _add_field(self, grid, panel, label, default):
        grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl = wx.TextCtrl(panel, value=default, size=(120, -1))
        grid.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    # ── Preview drawing ──────────────────────────────────────────────

    def _draw_empty_preview(self):
        ax = self._ax_prev
        ax.clear()
        ax.set_facecolor(_C_BG)
        ax.text(0.5, 0.5, "Click 'Synthesize'\nto generate preview",
                ha='center', va='center', fontsize=12, color='#666',
                transform=ax.transAxes)
        ax.set_aspect('equal')
        for sp in ax.spines.values(): sp.set_visible(False)
        ax.set_xticks([]); ax.set_yticks([])
        self._canvas.draw()

    def _draw_preview(self):
        if not HAS_MPL or self._profile is None:
            return
        from addon.footprint_gen import footprint_dimensions, _taper_polygon_mm

        spec = self._current_spec()
        dims = footprint_dimensions(spec)
        profile = self._profile

        ax = self._ax_prev
        ax.clear()
        ax.set_facecolor(_C_BG)

        L_s = dims["L_landing_start_mm"]
        L_b = dims["L_body_mm"]
        L_e = dims["L_landing_end_mm"]
        w_s = dims["w_start_mm"]
        w_e = dims["w_end_mm"]
        total = L_s + L_b + L_e

        # Use exact footprint polygon (same geometry as .kicad_mod)
        poly_pts = _taper_polygon_mm(spec)
        px = [p[0] for p in poly_pts]
        py = [p[1] for p in poly_pts]
        ax.fill(px, py, fc=_C_COPPER, ec='#ff5555', lw=0.6, alpha=0.85)

        # Origin crosshair
        ch = max(w_s, w_e) * 0.6
        ax.plot([0, 0], [-ch, ch], color=_C_ORIGIN, lw=0.5, alpha=0.5)
        ax.plot([-ch, ch], [0, 0], color=_C_ORIGIN, lw=0.5, alpha=0.5)

        # Subtle pad labels
        ax.text(0, w_s/2 + 0.12, "1", ha='center', fontsize=7, color='#aaa')
        body_end = L_s/2 + L_b
        ax.text(body_end + L_e/2, w_e/2 + 0.12, "1", ha='center', fontsize=7, color='#aaa')

        # Dimension annotations (CAD style)
        y_dim = -max(w_s, w_e)/2 - 0.4
        body_start = L_s / 2
        ax.annotate("", xy=(body_start, y_dim), xytext=(body_end, y_dim),
                     arrowprops=dict(arrowstyle="<->", color=_C_DIM, lw=0.8))
        ax.text((body_start+body_end)/2, y_dim-0.15, f"{L_b:.2f}",
                ha='center', fontsize=6, color=_C_DIM)
        ax.annotate("", xy=(-L_s/2, y_dim-0.6), xytext=(body_end+L_e, y_dim-0.6),
                     arrowprops=dict(arrowstyle="<->", color='#5577aa', lw=0.8))
        ax.text(total/2 - L_s/2, y_dim-0.75, f"{total:.2f} mm",
                ha='center', fontsize=6, color='#5577aa')

        # Grid (KiCad-like dots)
        margin = max(total, max(w_s, w_e)) * 0.15
        ax.set_xlim(-L_s/2 - margin, body_end + L_e + margin)
        ax.set_ylim(y_dim - 1.2, max(w_s, w_e)/2 + 0.5)
        ax.set_aspect('equal')
        ax.grid(True, color=_C_GRID, lw=0.3, alpha=0.5)
        for sp in ax.spines.values(): sp.set_color(_C_GRID)
        ax.tick_params(colors='#555', labelsize=6)
        self._canvas.draw()

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

    def _read_params(self):
        return {
            "ZS": float(self._zs.GetValue()),
            "ZL": float(self._zl.GetValue()),
            "Gamma_m": float(self._gm.GetValue()),
            "f_start": float(self._fstart.GetValue()) * 1e9,
            "f_stop": float(self._fstop.GetValue()) * 1e9,
            "length_margin": float(self._lm.GetValue()),
        }

    # ── Button handlers ──────────────────────────────────────────────

    def _on_synthesize(self, event):
        logger.info("Synthesize clicked")
        try:
            p = self._read_params()
            from addon.ui_main import synthesize_taper, SynthesisRequest

            self._settings.analysis.f_start_hz = p["f_start"]
            self._settings.analysis.f_stop_hz = p["f_stop"]
            self._settings.analysis.length_margin = p["length_margin"]

            request = SynthesisRequest(
                ZS_ohm=p["ZS"], ZL_ohm=p["ZL"], Gamma_m=p["Gamma_m"])
            result, report, profile = synthesize_taper(request, self._settings)

            self._profile = profile
            self._result = result
            logger.info("Synthesis OK: L=%.3f mm", profile.L * 1e3)

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
                f"L_body  = {dims['L_body_mm']:.3f} mm  (RF taper)",
                f"L_total = {dims['L_total_mm']:.3f} mm  (with landings)",
                "",
                f"w_start = {dims['w_start_mm']:.4f} mm",
                f"w_end   = {dims['w_end_mm']:.4f} mm",
                "",
                f"Max |S11| = {result.max_s11_db:.1f} dB",
                f"Max |S22| = {result.max_s22_db:.1f} dB",
                f"Worst IL  = {result.max_insertion_loss_db:.2f} dB",
                "",
                f"Source: Fast analytical model",
            ]
            self._results_text.SetValue("\n".join(lines))
            self._draw_preview()

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
            dlg = SParamPlotDialog(self, self._result, self._read_params())
            dlg.Show()
            logger.info("S-Parameter plot window created")
        except Exception as e:
            logger.error("S-param plot failed: %s\n%s", e, traceback.format_exc())
            wx.MessageBox(f"S-parameter plot failed:\n{e}", "Error",
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


# ── S-Parameter Plot Dialog ──────────────────────────────────────────

class SParamPlotDialog(wx.Frame):
    """Separate interactive S-parameter plot window."""

    def __init__(self, parent, result: AssemblyResult, params: dict):
        super().__init__(parent, title="S-Parameters", size=(700, 500))
        self._result = result
        self._params = params

        if not HAS_MPL:
            wx.MessageBox("matplotlib not available", "Error", wx.OK | wx.ICON_ERROR)
            self.Destroy()
            return

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        fig = Figure(figsize=(7, 5), dpi=100)
        canvas = FigureCanvas(panel, -1, fig)
        sizer.Add(canvas, 1, wx.EXPAND)
        panel.SetSizer(sizer)

        ax = fig.add_subplot(111)
        f = result.freqs / 1e9

        ax.plot(f, result.s11_db, color=_C_S11, lw=1.5, label="|S₁₁|")
        ax.plot(f, result.s21_db, color=_C_S21, lw=1.5, label="|S₂₁|")
        ax.plot(f, result.s22_db, color=_C_S22, lw=1.5, label="|S₂₂|")

        gm = params["Gamma_m"]
        target_db = 20 * np.log10(gm) if gm > 0 else -60
        ax.axhline(target_db, color=_C_TARGET, ls='--', lw=1,
                    label=f"Target Γm={gm:.3f} ({target_db:.1f} dB)")

        # Markers
        i_worst_s11 = np.argmax(result.s11_db)
        ax.plot(f[i_worst_s11], result.s11_db[i_worst_s11], 'v',
                color=_C_S11, ms=8)
        i_worst_il = np.argmax(result.s21_db)
        ax.plot(f[i_worst_il], result.s21_db[i_worst_il], '^',
                color=_C_S21, ms=8)

        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_title(
            f"S-Parameters — z₀₁={result.z01:.0f}Ω, z₀₂={result.z02:.0f}Ω  "
            f"[Fast model]")
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        canvas.draw()
        self.Show()


# ── Stackup Settings Dialog ──────────────────────────────────────────

class StackupDialog(wx.Dialog):
    """Display/edit stackup parameters (read-only in v1)."""

    def __init__(self, parent, settings: RFProjectSettings):
        super().__init__(parent, title="Stackup Settings", size=(380, 350))
        sizer = wx.BoxSizer(wx.VERTICAL)

        box = wx.StaticBoxSizer(wx.VERTICAL, self, "RO4350B 10mil (default)")
        grid = wx.FlexGridSizer(cols=2, hgap=12, vgap=6)
        grid.AddGrowableCol(1)

        s = settings.stackup
        fields = [
            ("Substrate height:", f"{s.h_sub_m*1e6:.1f} µm"),
            ("Dk (εr):", f"{s.dk_10ghz:.2f}"),
            ("Df (tan δ):", f"{s.df_10ghz:.4f}"),
            ("Cu thickness:", f"{s.t_cu_m*1e6:.1f} µm"),
            ("Cu roughness (Rq):", f"{s.rq_m*1e6:.2f} µm"),
            ("Soldermask:", "Not modeled (v1)"),
        ]
        for label, value in fields:
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(wx.StaticText(self, label=value), 0, wx.ALIGN_CENTER_VERTICAL)

        box.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(box, 1, wx.EXPAND | wx.ALL, 10)

        note = wx.StaticText(self,
            label="Stackup editing will be available in a future version.\n"
                  "Currently using RO4350B 10mil defaults.")
        note.SetForegroundColour(wx.Colour(120, 120, 120))
        sizer.Add(note, 0, wx.ALL, 10)

        btn = wx.Button(self, wx.ID_OK, "OK")
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        self.SetSizer(sizer)
        self.CenterOnParent()


# For backward compatibility / standalone testing
TaperDialog = TaperWizard
