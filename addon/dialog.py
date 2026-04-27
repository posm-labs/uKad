"""KiCad-style wxPython dialog for Klopfenstein taper tool.

Provides:
  - RF parameter input panel
  - Interactive S-parameter plot (embedded matplotlib with zoom/pan)
  - Geometry preview
  - Headline metrics and warnings
  - Insert / Export / Cancel buttons

Designed to run inside KiCad's Python environment.
Can also be tested standalone with mock data.

All KiCad interaction goes through ``addon.kicad_compat`` — this module
does NOT import ``pcbnew`` directly.
"""

from __future__ import annotations

import pathlib
from typing import Optional, List, Tuple

try:
    import wx
    import wx.lib.scrolledpanel as scrolled
    HAS_WX = True
except ImportError:
    HAS_WX = False

import numpy as np

# Matplotlib with WXAgg backend for embedding
try:
    import matplotlib
    matplotlib.use("WXAgg")
    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
    from matplotlib.backends.backend_wxagg import NavigationToolbar2WxAgg as NavigationToolbar
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from rfcore.config import RFProjectSettings
from rfcore.taper_assembly import AssemblyResult
from rfcore.klopfenstein import KlopfensteinProfile
from addon.selection import SelectionResult


# ── Colors ───────────────────────────────────────────────────────────────
_C_S11 = "#1f77b4"
_C_S21 = "#2ca02c"
_C_S22 = "#d62728"
_C_TARGET = "#888888"


class TaperDialog(wx.Dialog):
    """Main taper synthesis dialog.

    Parameters
    ----------
    parent : wx.Window or None
    board : pcbnew.BOARD or None (for standalone testing)
    selection : SelectionResult
    settings : RFProjectSettings or None
    """

    def __init__(
        self,
        parent,
        board=None,
        selection: Optional[SelectionResult] = None,
        settings: Optional[RFProjectSettings] = None,
        kicad_ver: Optional[Tuple[int, int, int]] = None,
    ):
        if not HAS_WX:
            raise RuntimeError("wxPython is required for the dialog.")

        super().__init__(
            parent,
            title="RF Klopfenstein Taper Tool",
            size=(1000, 700),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self._board = board
        self._selection = selection or SelectionResult()
        self._settings = settings or RFProjectSettings()
        self._result: Optional[AssemblyResult] = None
        self._profile: Optional[KlopfensteinProfile] = None
        self._kicad_ver = kicad_ver or (0, 0, 0)

        self._build_ui()
        self._populate_from_selection()

        self.Centre()

    # ─── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left panel: parameters + metrics
        left_panel = self._build_left_panel()
        main_sizer.Add(left_panel, 0, wx.EXPAND | wx.ALL, 5)

        # Right panel: plots
        right_panel = self._build_right_panel()
        main_sizer.Add(right_panel, 1, wx.EXPAND | wx.ALL, 5)

        # Bottom buttons
        outer_sizer = wx.BoxSizer(wx.VERTICAL)
        outer_sizer.Add(main_sizer, 1, wx.EXPAND)
        outer_sizer.Add(self._build_buttons(), 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(outer_sizer)

    def _build_left_panel(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── RF Parameters ──
        param_box = wx.StaticBox(panel, label="RF Parameters")
        param_sizer = wx.StaticBoxSizer(param_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        grid.AddGrowableCol(1)

        self._zs = self._add_param(grid, panel, "ZS (Ω):", "50.0")
        self._zl = self._add_param(grid, panel, "ZL (Ω):", "75.0")
        self._gm = self._add_param(grid, panel, "Γm:", "0.05")
        self._fstart = self._add_param(grid, panel, "f_start (GHz):", "1.0")
        self._fstop = self._add_param(grid, panel, "f_stop (GHz):", "10.0")
        self._margin = self._add_param(grid, panel, "Length margin:", "1.0")

        param_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(param_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # ── Layout ──
        layout_box = wx.StaticBox(panel, label="Layout")
        layout_sizer = wx.StaticBoxSizer(layout_box, wx.VERTICAL)
        lgrid = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        lgrid.AddGrowableCol(1)

        self._layer = self._add_param(lgrid, panel, "Layer:", "F.Cu")
        self._net = self._add_param(lgrid, panel, "Net:", "")

        layout_sizer.Add(lgrid, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(layout_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # ── Compute button ──
        self._btn_compute = wx.Button(panel, label="Compute")
        self._btn_compute.Bind(wx.EVT_BUTTON, self._on_compute)
        sizer.Add(self._btn_compute, 0, wx.EXPAND | wx.BOTTOM, 10)

        # ── Metrics ──
        metrics_box = wx.StaticBox(panel, label="Metrics")
        metrics_sizer = wx.StaticBoxSizer(metrics_box, wx.VERTICAL)
        self._metrics_text = wx.StaticText(panel, label="(click Compute)")
        self._metrics_text.SetFont(
            wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        metrics_sizer.Add(self._metrics_text, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(metrics_sizer, 1, wx.EXPAND)

        # ── S-param toggles ──
        toggle_box = wx.StaticBox(panel, label="Plot Traces")
        toggle_sizer = wx.StaticBoxSizer(toggle_box, wx.HORIZONTAL)
        self._chk_s11 = wx.CheckBox(panel, label="S11")
        self._chk_s21 = wx.CheckBox(panel, label="S21")
        self._chk_s22 = wx.CheckBox(panel, label="S22")
        self._chk_s11.SetValue(True)
        self._chk_s21.SetValue(True)
        self._chk_s22.SetValue(True)
        for chk in (self._chk_s11, self._chk_s21, self._chk_s22):
            chk.Bind(wx.EVT_CHECKBOX, self._on_toggle_trace)
            toggle_sizer.Add(chk, 0, wx.ALL, 5)
        sizer.Add(toggle_sizer, 0, wx.EXPAND | wx.TOP, 5)

        panel.SetSizer(sizer)
        panel.SetMinSize((240, -1))
        return panel

    def _build_right_panel(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        if HAS_MPL:
            # S-parameter plot
            self._fig = Figure(figsize=(7, 4), dpi=100)
            self._ax = self._fig.add_subplot(111)
            self._ax.set_xlabel("Frequency (GHz)")
            self._ax.set_ylabel("Magnitude (dB)")
            self._ax.set_title("S-Parameters")
            self._ax.grid(True, alpha=0.3)

            self._canvas = FigureCanvas(panel, -1, self._fig)
            self._toolbar = NavigationToolbar(self._canvas)
            self._toolbar.Realize()

            sizer.Add(self._canvas, 1, wx.EXPAND)
            sizer.Add(self._toolbar, 0, wx.EXPAND)
        else:
            sizer.Add(
                wx.StaticText(panel, label="matplotlib not available — no plot"),
                1, wx.EXPAND | wx.ALL, 20,
            )

        panel.SetSizer(sizer)
        return panel

    def _build_buttons(self) -> wx.BoxSizer:
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._btn_insert = wx.Button(self, label="Insert")
        self._btn_insert.Bind(wx.EVT_BUTTON, self._on_insert)
        self._btn_insert.Enable(False)

        self._btn_export = wx.Button(self, label="Export Reports...")
        self._btn_export.Bind(wx.EVT_BUTTON, self._on_export)
        self._btn_export.Enable(False)

        btn_cancel = wx.Button(self, wx.ID_CANCEL, label="Cancel")

        sizer.Add(self._btn_insert, 0, wx.ALL, 5)
        sizer.Add(self._btn_export, 0, wx.ALL, 5)
        sizer.AddStretchSpacer()
        sizer.Add(btn_cancel, 0, wx.ALL, 5)

        return sizer

    def _add_param(self, grid, parent, label, default) -> wx.TextCtrl:
        grid.Add(wx.StaticText(parent, label=label), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        ctrl = wx.TextCtrl(parent, value=default, size=(100, -1))
        grid.Add(ctrl, 0, wx.EXPAND)
        return ctrl

    # ─── Selection population ────────────────────────────────────────

    def _populate_from_selection(self):
        sel = self._selection
        if sel.layer:
            self._layer.SetValue(sel.layer)
        if sel.net_name:
            self._net.SetValue(sel.net_name)
        if sel.mode == "auto" and sel.valid:
            # Pre-compute impedance from widths if we have them
            pass  # ZS/ZL come from RF design intent, not trace widths

    # ─── Event handlers ──────────────────────────────────────────────

    def _on_compute(self, event):
        """Run taper synthesis with current parameters."""
        try:
            from rfcore.microstrip import MicrostripModel

            ZS = float(self._zs.GetValue())
            ZL = float(self._zl.GetValue())
            Gamma_m = float(self._gm.GetValue())
            f_start = float(self._fstart.GetValue()) * 1e9
            f_stop = float(self._fstop.GetValue()) * 1e9
            margin = float(self._margin.GetValue())

            self._settings.analysis.f_start_hz = f_start
            self._settings.analysis.f_stop_hz = f_stop
            self._settings.analysis.length_margin = margin

            ms = MicrostripModel.from_settings(self._settings)

            self._profile = KlopfensteinProfile(
                ZS=ZS, ZL=ZL, Gamma_m=Gamma_m,
                microstrip=ms,
                f_min=f_start,
                f_geom=self._settings.analysis.f_geom,
                length_margin=margin,
            )

            from rfcore.taper_assembly import TaperAssembly
            assembly = TaperAssembly(self._settings, self._profile, ms)
            self._result = assembly.evaluate()

            self._update_metrics()
            self._update_plot()
            self._btn_insert.Enable(True)
            self._btn_export.Enable(True)

        except Exception as e:
            wx.MessageBox(str(e), "Compute Error", wx.ICON_ERROR)

    def _on_toggle_trace(self, event):
        if self._result is not None:
            self._update_plot()

    def _on_insert(self, event):
        """Insert taper into the active board."""
        if self._board is None:
            wx.MessageBox(
                "No board connection. Cannot insert.",
                "Insert Error", wx.ICON_ERROR,
            )
            return

        if self._profile is None or self._result is None:
            return

        try:
            from addon.live_insert import prepare_insertion
            from addon.board_insert import insert_taper_zone

            plan = prepare_insertion(self._profile, self._selection)

            # Print debug info to scripting console
            print(plan.debug_summary())

            # Show warnings before inserting
            if plan.warnings:
                warn_text = "\n".join(f"• {w}" for w in plan.warnings)
                result = wx.MessageBox(
                    f"Warnings:\n{warn_text}\n\nProceed with insertion?",
                    "Insertion Warnings",
                    wx.YES_NO | wx.ICON_WARNING,
                )
                if result != wx.YES:
                    return

            zone = insert_taper_zone(
                self._board, plan.polygon,
                layer=plan.layer,
                net_name=plan.net_name,
            )

            # Save sidecar metadata
            self._save_sidecar()

            msg = (
                f"Taper inserted successfully.\n"
                f"Length: {plan.L_actual_m*1e3:.2f} mm\n"
                f"Max |S11|: {self._result.max_s11_db:.1f} dB\n"
            )
            if plan.connects_end:
                msg += "Both endpoints connected."
            else:
                msg += (
                    f"Anchored at start only.\n"
                    f"Gap: {plan.L_gap_m*1e3:.1f} mm, "
                    f"Taper: {plan.L_actual_m*1e3:.1f} mm"
                )

            wx.MessageBox(msg, "Success", wx.ICON_INFORMATION)
            self.EndModal(wx.ID_OK)

        except Exception as e:
            wx.MessageBox(str(e), "Insert Error", wx.ICON_ERROR)

    def _on_export(self, event):
        """Export all reports to a directory."""
        dlg = wx.DirDialog(self, "Choose export directory")
        if dlg.ShowModal() == wx.ID_OK:
            export_dir = dlg.GetPath()
            try:
                self._export_all(pathlib.Path(export_dir))
                wx.MessageBox(
                    f"Reports exported to:\n{export_dir}",
                    "Export Complete", wx.ICON_INFORMATION,
                )
            except Exception as e:
                wx.MessageBox(str(e), "Export Error", wx.ICON_ERROR)
        dlg.Destroy()

    # ─── Plot update ─────────────────────────────────────────────────

    def _update_plot(self):
        if not HAS_MPL or self._result is None:
            return

        ax = self._ax
        ax.clear()

        freqs_ghz = self._result.freqs / 1e9
        z01 = self._result.z01
        z02 = self._result.z02

        if self._chk_s11.GetValue():
            ax.plot(freqs_ghz, self._result.s11_db, color=_C_S11,
                    linewidth=1.5, label=f"|S11| (z01={z01:.0f}Ω)")
            # Worst S11 marker
            idx = int(np.argmax(self._result.s11_db))
            ax.plot(freqs_ghz[idx], self._result.s11_db[idx], "v",
                    color=_C_S11, markersize=8)

        if self._chk_s21.GetValue():
            ax.plot(freqs_ghz, self._result.s21_db, color=_C_S21,
                    linewidth=1.5, label="|S21|")
            # Worst IL marker
            idx = int(np.argmin(self._result.s21_db))
            ax.plot(freqs_ghz[idx], self._result.s21_db[idx], "v",
                    color=_C_S21, markersize=8)

        if self._chk_s22.GetValue():
            ax.plot(freqs_ghz, self._result.s22_db, color=_C_S22,
                    linewidth=1.5, label=f"|S22| (z02={z02:.0f}Ω)")

        # Γm target line
        Gamma_m = float(self._gm.GetValue())
        if Gamma_m > 0:
            target_db = 20.0 * np.log10(Gamma_m)
            ax.axhline(target_db, color=_C_TARGET, linestyle="--",
                       linewidth=0.8, label=f"Γm target = {target_db:.1f} dB")

        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_title(f"S-Parameters — z01={z01:.0f}Ω, z02={z02:.0f}Ω")
        ax.legend(fontsize=8, loc="best")
        ax.grid(True, alpha=0.3)

        self._canvas.draw()

    def _update_metrics(self):
        if self._result is None or self._profile is None:
            return

        r = self._result
        p = self._profile

        text = (
            f"Max |S11|:   {r.max_s11_db:.2f} dB\n"
            f"Max |S22|:   {r.max_s22_db:.2f} dB\n"
            f"Worst IL:    {r.max_insertion_loss_db:.2f} dB\n"
            f"\n"
            f"z01 = {r.z01:.0f} Ω (ZS)\n"
            f"z02 = {r.z02:.0f} Ω (ZL)\n"
            f"\n"
            f"Length:      {p.L*1e3:.2f} mm\n"
            f"Segments:    {len(r.body_segments)}\n"
        )

        if r.warnings.messages:
            text += "\n⚠ Warnings:\n"
            for w in r.warnings.messages:
                text += f"  • {w.text}\n"

        self._metrics_text.SetLabel(text)

    # ─── Export ───────────────────────────────────────────────────────

    def _export_all(self, output_dir: pathlib.Path):
        """Export all report files to the given directory."""
        if self._result is None or self._profile is None:
            raise ValueError("No computed result to export.")

        output_dir.mkdir(parents=True, exist_ok=True)

        # Text / JSON report
        from rfcore.reports import TaperReport
        report = TaperReport(
            self._settings, self._profile, self._result, [], [],
        )
        report.save_text(str(output_dir / "report.txt"))
        report.save_json(str(output_dir / "report.json"))

        # PNG plots
        from rfcore.plots import generate_all_plots
        generate_all_plots(self._result, self._profile, output_dir / "plots")

        # CSV
        from rfcore.export.csv_export import export_frequency_csv, export_geometry_csv
        export_frequency_csv(self._result, output_dir / "frequency_data.csv")
        export_geometry_csv(self._profile, output_dir / "geometry_data.csv")

        # Touchstone
        from rfcore.export.touchstone import export_touchstone_v2, export_touchstone_v1
        export_touchstone_v2(self._result, output_dir / "taper.ts")
        export_touchstone_v1(self._result, output_dir / "taper_compat.s2p")

        # Geometry
        from rfcore.export.geometry import (
            generate_taper_polygon, export_svg, export_png_preview,
            export_kicad_mod,
        )
        polygon = generate_taper_polygon(self._profile)
        export_svg(polygon, output_dir / "taper.svg")
        export_png_preview(polygon, output_dir / "taper_preview.png")
        export_kicad_mod(polygon, output_dir / "taper.kicad_mod")

    # ─── Sidecar ─────────────────────────────────────────────────────

    def _save_sidecar(self):
        """Save sidecar metadata alongside the board file."""
        if self._board is None:
            return
        try:
            from addon.kicad_compat import get_board_filename
            from addon.ui_main import save_settings, save_report
            from rfcore.reports import TaperReport

            board_path = get_board_filename(self._board)
            if not board_path:
                return

            save_settings(board_path, self._settings)

            report = TaperReport(
                self._settings, self._profile, self._result, [], [],
            )
            save_report(board_path, report)
        except Exception:
            pass  # Don't block insertion if sidecar fails


# ── Standalone test entry point ──────────────────────────────────────────

def run_standalone_test():
    """Run the dialog standalone for testing (no KiCad required)."""
    if not HAS_WX:
        print("wxPython not available. Cannot run dialog test.")
        return

    app = wx.App()
    sel = SelectionResult(
        mode="manual", valid=True,
        layer="F.Cu", net_name="SIG_RF",
        start_x_m=0.01, start_y_m=0.02,
        end_x_m=0.07, end_y_m=0.02,
        start_width_m=0.5e-3, end_width_m=0.22e-3,
    )
    dlg = TaperDialog(None, board=None, selection=sel)
    dlg.ShowModal()
    dlg.Destroy()
    app.MainLoop()


if __name__ == "__main__":
    run_standalone_test()
