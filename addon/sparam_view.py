"""Interactive S-parameter viewer using Plotly HTML.

Generates a self-contained HTML page with Plotly.js and opens it in
either wx.html2.WebView (if available) or the default browser.

The viewer provides:
  - Mouse wheel zoom at cursor
  - Click-drag pan
  - Hover crosshair with frequency + value readout
  - Legend click to toggle S11/S21/S22
  - Export as PNG/SVG from Plotly toolbar

No RF computation happens here. All data comes from a pre-computed
AssemblyResult object.
"""

from __future__ import annotations

import json
import logging
import pathlib
import tempfile
import webbrowser
from typing import Optional

import numpy as np

from rfcore.taper_assembly import AssemblyResult

logger = logging.getLogger(__name__)

# Plotly.js CDN — structured so bundled file can replace this later
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.32.0.min.js"


def _plotly_js_src() -> str:
    """Return the Plotly.js <script> tag.

    Uses CDN by default. To bundle offline, place plotly.min.js next to
    this file and change this function to return a file:// URI or inline.
    """
    bundled = pathlib.Path(__file__).parent / "plotly.min.js"
    if bundled.exists():
        return f'<script src="file://{bundled}"></script>'
    return f'<script src="{_PLOTLY_CDN}"></script>'


def generate_sparam_html(result: AssemblyResult, params: dict) -> str:
    """Generate self-contained Plotly HTML for S-parameter display.

    Parameters
    ----------
    result : AssemblyResult
        Pre-computed S-parameter data.
    params : dict
        Must contain 'Gamma_m' and optionally 'f_start', 'f_stop'.

    Returns
    -------
    str : Complete HTML document.
    """
    f_ghz = (result.freqs / 1e9).tolist()
    s11 = result.s11_db.tolist()
    s21 = result.s21_db.tolist()
    s22 = result.s22_db.tolist()

    gm = params.get("Gamma_m", 0.05)
    target_db = float(20 * np.log10(gm)) if gm > 0 else -60.0

    # Worst-case markers
    i_s11 = int(np.argmax(result.s11_db))
    i_il = int(np.argmin(result.s21_db))

    traces = json.dumps([
        {
            "x": f_ghz, "y": s11, "name": "|S11|",
            "line": {"color": "#1f77b4", "width": 2},
            "hovertemplate": "f=%{x:.3f} GHz<br>S11=%{y:.2f} dB<extra></extra>",
        },
        {
            "x": f_ghz, "y": s21, "name": "|S21|",
            "line": {"color": "#2ca02c", "width": 2},
            "hovertemplate": "f=%{x:.3f} GHz<br>S21=%{y:.2f} dB<extra></extra>",
        },
        {
            "x": f_ghz, "y": s22, "name": "|S22|",
            "line": {"color": "#d62728", "width": 2},
            "hovertemplate": "f=%{x:.3f} GHz<br>S22=%{y:.2f} dB<extra></extra>",
        },
        {
            "x": [f_ghz[0], f_ghz[-1]], "y": [target_db, target_db],
            "name": f"Target Gm={gm:.3f} ({target_db:.1f} dB)",
            "line": {"color": "#888", "width": 1, "dash": "dash"},
            "hoverinfo": "skip",
        },
        {
            "x": [f_ghz[i_s11]], "y": [s11[i_s11]],
            "name": f"Worst S11: {s11[i_s11]:.1f} dB @ {f_ghz[i_s11]:.2f} GHz",
            "mode": "markers",
            "marker": {"color": "#1f77b4", "size": 10, "symbol": "triangle-down"},
            "hovertemplate": "Worst S11<br>f=%{x:.3f} GHz<br>%{y:.2f} dB<extra></extra>",
        },
        {
            "x": [f_ghz[i_il]], "y": [s21[i_il]],
            "name": f"Worst IL: {s21[i_il]:.2f} dB @ {f_ghz[i_il]:.2f} GHz",
            "mode": "markers",
            "marker": {"color": "#2ca02c", "size": 10, "symbol": "triangle-up"},
            "hovertemplate": "Worst IL<br>f=%{x:.3f} GHz<br>%{y:.2f} dB<extra></extra>",
        },
    ])

    layout = json.dumps({
        "title": f"S-Parameters — z01={result.z01:.0f} Ω, z02={result.z02:.0f} Ω  [Fast analytical model]",
        "xaxis": {"title": "Frequency (GHz)", "gridcolor": "#ddd"},
        "yaxis": {"title": "Magnitude (dB)", "gridcolor": "#ddd"},
        "hovermode": "x unified",
        "legend": {"orientation": "h", "y": -0.15},
        "margin": {"t": 50, "b": 80, "l": 60, "r": 20},
        "plot_bgcolor": "#fafafa",
        "paper_bgcolor": "#fff",
    })

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>S-Parameters — uKad Klopfenstein Taper</title>
{_plotly_js_src()}
<style>
body {{ margin: 0; font-family: -apple-system, sans-serif; }}
#plot {{ width: 100vw; height: 100vh; }}
</style>
</head>
<body>
<div id="plot"></div>
<script>
Plotly.newPlot('plot', {traces}, {layout}, {{
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToAdd: ['hoverClosestCartesian', 'hoverCompareCartesian'],
}});
</script>
</body>
</html>"""


def show_sparams(result: AssemblyResult, params: dict,
                 parent=None) -> None:
    """Show interactive S-parameter plot.

    Tries wx.html2.WebView first (embedded in dialog), then falls back
    to opening in the default web browser.

    Parameters
    ----------
    result : AssemblyResult
    params : dict with 'Gamma_m'
    parent : wx window or None
    """
    html = generate_sparam_html(result, params)

    # Write to temp file (both paths need it)
    tmp = pathlib.Path(tempfile.gettempdir()) / "ukad_sparams.html"
    tmp.write_text(html, encoding="utf-8")
    logger.info("S-param HTML written: %s", tmp)

    # Try embedded WebView
    try:
        import wx
        import wx.html2

        dlg = wx.Dialog(parent, title="S-Parameters",
                        size=(900, 600),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        wv = wx.html2.WebView.New(dlg)
        wv.LoadURL(f"file://{tmp}")
        sizer.Add(wv, 1, wx.EXPAND)

        btn = wx.Button(dlg, wx.ID_CLOSE, "Close")
        btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        dlg.SetSizer(sizer)
        dlg.CenterOnParent()

        logger.info("Opening S-param plot in WebView")
        dlg.ShowModal()
        dlg.Destroy()
        return
    except Exception as e:
        logger.info("WebView not available (%s), falling back to browser", e)

    # Fallback: open in default browser
    url = f"file://{tmp}"
    webbrowser.open(url)
    logger.info("Opened S-param plot in browser: %s", url)

    # If wx available, show info dialog
    try:
        import wx
        wx.MessageBox(
            f"S-parameter plot opened in your web browser.\n\n"
            f"File: {tmp}\n\n"
            f"You can zoom, pan, hover, and toggle traces.",
            "S-Parameters", wx.OK | wx.ICON_INFORMATION)
    except ImportError:
        pass
