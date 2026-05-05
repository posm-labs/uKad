"""wx-native footprint preview canvas with interactive zoom/pan.

Replaces matplotlib for footprint preview. Uses wx.GraphicsContext for
anti-aliased rendering with KiCad-like appearance.

Interaction:
  Mouse wheel      — zoom at cursor
  Left-drag        — pan (on empty area) or select (on copper)
  Middle-drag      — pan
  Double-click     — fit-to-view
  Right-click      — context menu (fit view, reset)

No RF computation happens during any paint/zoom/pan/hover event.
All geometry is pre-computed and cached as polygon point lists.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

try:
    import wx
except ImportError:
    wx = None  # type: ignore


# ── Colors (KiCad-inspired) ──
_BG = (26, 26, 46)           # dark canvas
_GRID = (42, 42, 74)         # subtle grid lines
_COPPER = (204, 51, 51)      # F.Cu red
_COPPER_EDGE = (255, 85, 85) # copper outline
_ORIGIN = (200, 200, 200)    # crosshair
_DIM = (102, 136, 204)       # dimension annotations
_DIM2 = (85, 119, 170)       # total dimension
_PAD_LABEL = (170, 170, 170) # pad number text
_HOVER_INFO = (200, 200, 200)
_SELECT_HL = (255, 255, 100, 80)  # selection highlight


class FootprintCanvas(wx.Panel):
    """Interactive footprint preview canvas with zoom/pan/hover."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        # Geometry data (set via set_geometry)
        self._polygon: List[Tuple[float, float]] = []
        self._dims: Optional[dict] = None
        self._has_geometry = False

        # Viewport transform: screen = (world - offset) * scale
        self._scale = 1.0       # pixels per mm
        self._offset_x = 0.0   # world x at screen left (mm)
        self._offset_y = 0.0   # world y at screen top (mm)

        # Interaction state
        self._dragging = False
        self._drag_start_screen = (0, 0)
        self._drag_start_offset = (0.0, 0.0)
        self._mouse_world = (0.0, 0.0)
        self._hover_on_copper = False

        # Grid
        self._grid_spacing_mm = 1.0  # auto-adjusted

        # Bind events
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_dclick)
        self.Bind(wx.EVT_MIDDLE_DOWN, self._on_mid_down)
        self.Bind(wx.EVT_MIDDLE_UP, self._on_mid_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)

    # ── Public API ──

    def set_geometry(self, polygon_pts: List[Tuple[float, float]],
                     dims: dict) -> None:
        """Set the footprint geometry for display.

        polygon_pts: closed polygon in footprint-local mm coordinates.
        dims: dict from footprint_dimensions().

        This is the ONLY data entry point. No RF code runs here.
        """
        self._polygon = list(polygon_pts)
        self._dims = dict(dims)
        self._has_geometry = True
        self.fit_view()

    def clear_geometry(self) -> None:
        self._polygon = []
        self._dims = None
        self._has_geometry = False
        self.Refresh()

    def fit_view(self) -> None:
        """Reset viewport to show entire footprint with margin."""
        if not self._polygon:
            self.Refresh()
            return

        xs = [p[0] for p in self._polygon]
        ys = [p[1] for p in self._polygon]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)

        # Add margin
        dx = (x_max - x_min) or 1.0
        dy = (y_max - y_min) or 1.0
        margin = max(dx, dy) * 0.15
        x_min -= margin
        x_max += margin
        y_min -= margin * 2  # extra space for dimension annotations
        y_max += margin

        w, h = self.GetClientSize()
        if w <= 0 or h <= 0:
            return

        sx = w / (x_max - x_min) if (x_max - x_min) > 0 else 1.0
        sy = h / (y_max - y_min) if (y_max - y_min) > 0 else 1.0
        self._scale = min(sx, sy)
        self._offset_x = x_min - (w / self._scale - (x_max - x_min)) / 2
        self._offset_y = y_min - (h / self._scale - (y_max - y_min)) / 2

        self._update_grid_spacing()
        self.Refresh()

    # ── Coordinate transforms ──

    def _world_to_screen(self, wx_, wy):
        sx = (wx_ - self._offset_x) * self._scale
        sy = (wy - self._offset_y) * self._scale
        return sx, sy

    def _screen_to_world(self, sx, sy):
        wx_ = sx / self._scale + self._offset_x
        wy = sy / self._scale + self._offset_y
        return wx_, wy

    def _update_grid_spacing(self):
        # Choose grid so lines are ~40-120 px apart
        target_px = 60
        world_per_px = 1.0 / self._scale if self._scale > 0 else 1.0
        raw = target_px * world_per_px
        # Snap to 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, ...
        decades = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50]
        self._grid_spacing_mm = min(decades, key=lambda d: abs(d - raw))

    # ── Point-in-polygon test ──

    def _point_in_polygon(self, px, py) -> bool:
        """Ray-casting point-in-polygon for hover/select."""
        poly = self._polygon
        n = len(poly)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # ── Event handlers ──

    def _on_size(self, event):
        if self._has_geometry:
            self.fit_view()
        else:
            self.Refresh()
        event.Skip()

    def _on_wheel(self, event):
        if not self._has_geometry:
            return
        # Zoom at cursor position
        sx, sy = event.GetPosition()
        wx_, wy = self._screen_to_world(sx, sy)

        factor = 1.15 if event.GetWheelRotation() > 0 else 1 / 1.15
        self._scale *= factor

        # Adjust offset so world point under cursor stays fixed
        self._offset_x = wx_ - sx / self._scale
        self._offset_y = wy - sy / self._scale

        self._update_grid_spacing()
        self.Refresh()

    def _on_left_down(self, event):
        self._dragging = True
        self._drag_start_screen = event.GetPosition()
        self._drag_start_offset = (self._offset_x, self._offset_y)
        self.CaptureMouse()

    def _on_left_up(self, event):
        if self._dragging:
            self._dragging = False
            if self.HasCapture():
                self.ReleaseMouse()

    def _on_dclick(self, event):
        self.fit_view()

    def _on_mid_down(self, event):
        self._dragging = True
        self._drag_start_screen = event.GetPosition()
        self._drag_start_offset = (self._offset_x, self._offset_y)
        self.CaptureMouse()

    def _on_mid_up(self, event):
        if self._dragging:
            self._dragging = False
            if self.HasCapture():
                self.ReleaseMouse()

    def _on_motion(self, event):
        sx, sy = event.GetPosition()
        self._mouse_world = self._screen_to_world(sx, sy)

        if self._dragging:
            dx = sx - self._drag_start_screen[0]
            dy = sy - self._drag_start_screen[1]
            self._offset_x = self._drag_start_offset[0] - dx / self._scale
            self._offset_y = self._drag_start_offset[1] - dy / self._scale
            self.Refresh()
        else:
            # Check hover
            old_hover = self._hover_on_copper
            self._hover_on_copper = self._point_in_polygon(*self._mouse_world)
            if old_hover != self._hover_on_copper:
                self.Refresh()

    def _on_right_down(self, event):
        menu = wx.Menu()
        fit_id = wx.NewId()
        menu.Append(fit_id, "Fit View")
        self.Bind(wx.EVT_MENU, lambda e: self.fit_view(), id=fit_id)
        self.PopupMenu(menu, event.GetPosition())
        menu.Destroy()

    # ── Painting ──

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return

        w, h = self.GetClientSize()
        if w <= 0 or h <= 0:
            return

        # Background
        gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(*_BG))))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.DrawRectangle(0, 0, w, h)

        if not self._has_geometry:
            self._draw_empty_message(gc, w, h)
            return

        self._draw_grid(gc, w, h)
        self._draw_origin(gc)
        self._draw_copper(gc)
        self._draw_dimensions(gc)
        self._draw_pad_labels(gc)
        self._draw_hover_info(gc, w, h)

    def _draw_empty_message(self, gc, w, h):
        gc.SetFont(gc.CreateFont(wx.Font(12, wx.FONTFAMILY_DEFAULT,
                   wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour(100, 100, 100)))
        text = "Click 'Synthesize' to generate preview"
        tw, th, _, _ = gc.GetFullTextExtent(text)
        gc.DrawText(text, (w - tw) / 2, (h - th) / 2)

    def _draw_grid(self, gc, w, h):
        gs = self._grid_spacing_mm
        if gs <= 0 or self._scale <= 0:
            return

        pen = gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(*_GRID)).Width(1))
        gc.SetPen(pen)

        # Visible world bounds
        x0, y0 = self._screen_to_world(0, 0)
        x1, y1 = self._screen_to_world(w, h)
        x_min, x_max = min(x0, x1), max(x0, x1)
        y_min, y_max = min(y0, y1), max(y0, y1)

        # Vertical lines
        x_start = math.floor(x_min / gs) * gs
        x = x_start
        while x <= x_max:
            sx, _ = self._world_to_screen(x, 0)
            gc.StrokeLine(sx, 0, sx, h)
            x += gs

        # Horizontal lines
        y_start = math.floor(y_min / gs) * gs
        y = y_start
        while y <= y_max:
            _, sy = self._world_to_screen(0, y)
            gc.StrokeLine(0, sy, w, sy)
            y += gs

    def _draw_origin(self, gc):
        cx, cy = self._world_to_screen(0, 0)
        length = 15  # pixels
        pen = gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(*_ORIGIN)).Width(1))
        gc.SetPen(pen)
        gc.StrokeLine(cx - length, cy, cx + length, cy)
        gc.StrokeLine(cx, cy - length, cx, cy + length)

    def _draw_copper(self, gc):
        if len(self._polygon) < 3:
            return

        path = gc.CreatePath()
        sx0, sy0 = self._world_to_screen(*self._polygon[0])
        path.MoveToPoint(sx0, sy0)
        for px, py in self._polygon[1:]:
            sx, sy = self._world_to_screen(px, py)
            path.AddLineToPoint(sx, sy)
        path.CloseSubpath()

        # Fill
        gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(*_COPPER, 220))))
        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(*_COPPER_EDGE)).Width(1)))
        gc.DrawPath(path)

        # Hover highlight
        if self._hover_on_copper:
            gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(*_SELECT_HL))))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawPath(path)

    def _draw_dimensions(self, gc):
        if not self._dims:
            return
        d = self._dims
        L_s = d["L_landing_start_mm"]
        L_b = d["L_body_mm"]
        L_e = d["L_landing_end_mm"]
        w_s = d["w_start_mm"]
        w_e = d["w_end_mm"]
        total = L_s + L_b + L_e

        body_start = L_s / 2
        body_end = body_start + L_b
        y_base = max(w_s, w_e) / 2

        # Body length dimension
        y_dim = y_base + 0.4
        self._draw_dim_line(gc, body_start, y_dim, body_end, y_dim,
                           f"{L_b:.2f}", _DIM)
        # Total length dimension
        y_dim2 = y_base + 0.8
        self._draw_dim_line(gc, -L_s / 2, y_dim2, body_end + L_e, y_dim2,
                           f"{total:.2f} mm", _DIM2)

    def _draw_dim_line(self, gc, x1, y1, x2, y2, label, color):
        sx1, sy1 = self._world_to_screen(x1, y1)
        sx2, sy2 = self._world_to_screen(x2, y2)

        pen = gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(*color)).Width(1))
        gc.SetPen(pen)
        gc.StrokeLine(sx1, sy1, sx2, sy2)
        # End ticks
        gc.StrokeLine(sx1, sy1 - 4, sx1, sy1 + 4)
        gc.StrokeLine(sx2, sy2 - 4, sx2, sy2 + 4)

        # Label
        font = gc.CreateFont(wx.Font(8, wx.FONTFAMILY_DEFAULT,
                             wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL),
                             wx.Colour(*color))
        gc.SetFont(font)
        tw, th, _, _ = gc.GetFullTextExtent(label)
        mx = (sx1 + sx2) / 2 - tw / 2
        my = sy1 - th - 2
        gc.DrawText(label, mx, my)

    def _draw_pad_labels(self, gc):
        if not self._dims:
            return
        d = self._dims
        font = gc.CreateFont(wx.Font(9, wx.FONTFAMILY_DEFAULT,
                             wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD),
                             wx.Colour(*_PAD_LABEL))
        gc.SetFont(font)

        # Pad 1 at origin
        sx1, sy1 = self._world_to_screen(0, -d["w_start_mm"] / 2 - 0.15)
        gc.DrawText("1", sx1 - 4, sy1)

        # Pad 1 at output
        sx2, sy2 = self._world_to_screen(d["pad2_x_mm"], -d["w_end_mm"] / 2 - 0.15)
        gc.DrawText("1", sx2 - 4, sy2)

    def _draw_hover_info(self, gc, w, h):
        mx, my = self._mouse_world
        info = f"({mx:.3f}, {my:.3f}) mm"
        if self._hover_on_copper:
            info += "  [F.Cu copper]"
            if self._dims:
                d = self._dims
                info += f"  w_in={d['w_start_mm']:.4f}  w_out={d['w_end_mm']:.4f}"

        font = gc.CreateFont(wx.Font(9, wx.FONTFAMILY_TELETYPE,
                             wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL),
                             wx.Colour(*_HOVER_INFO))
        gc.SetFont(font)
        tw, th, _, _ = gc.GetFullTextExtent(info)
        gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(26, 26, 46, 200))))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.DrawRectangle(4, h - th - 6, tw + 8, th + 4)
        gc.DrawText(info, 8, h - th - 4)
