"""Debug: dump raw selected track data from KiCad.

Run in KiCad Scripting Console:
  exec(open('/Users/mahdi1265/uKad/scripts/debug_selected_tracks.py').read())

This script ONLY reads and prints. It does NOT insert anything.
"""

import sys
import os

_PROJECT_ROOT = '/Users/mahdi1265/uKad'
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def debug_selected_tracks():
    """Dump all selected track info from the active board."""
    print("\n" + "=" * 70)
    print("  DEBUG: Raw Selected Track Data")
    print("=" * 70)

    # ── 1. KiCad version ──
    from addon.kicad_compat import (
        kicad_version, get_board, get_board_filename, to_mm, to_m,
    )

    ver = kicad_version()
    print(f"\nKiCad version: {ver[0]}.{ver[1]}.{ver[2]}")

    board = get_board()
    print(f"Board file: {get_board_filename(board)}")

    # ── 2. Raw track iteration ──
    from addon.kicad_compat import _ensure_pcbnew
    pcbnew = _ensure_pcbnew()

    all_tracks = list(board.GetTracks())
    print(f"\nTotal tracks on board: {len(all_tracks)}")

    selected_count = 0
    selected_tracks_raw = []

    for i, item in enumerate(all_tracks):
        is_sel = item.IsSelected()
        if is_sel:
            selected_count += 1

            is_track = isinstance(item, pcbnew.PCB_TRACK)
            is_via = isinstance(item, pcbnew.PCB_VIA)
            type_name = type(item).__name__

            start = item.GetStart()
            end = item.GetEnd()
            width = item.GetWidth()
            layer_name = item.GetLayerName()
            net_name = item.GetNetname()

            print(f"\n  --- Selected Item #{selected_count} ---")
            print(f"  Type:        {type_name}")
            print(f"  Is PCB_TRACK: {is_track}")
            print(f"  Is PCB_VIA:   {is_via}")
            print(f"  IsSelected(): {is_sel}")
            print(f"  Start (IU):  ({start.x}, {start.y})")
            print(f"  Start (mm):  ({to_mm(start.x):.4f}, {to_mm(start.y):.4f})")
            print(f"  Start (m):   ({to_m(start.x):.6f}, {to_m(start.y):.6f})")
            print(f"  End (IU):    ({end.x}, {end.y})")
            print(f"  End (mm):    ({to_mm(end.x):.4f}, {to_mm(end.y):.4f})")
            print(f"  End (m):     ({to_m(end.x):.6f}, {to_m(end.y):.6f})")
            print(f"  Width (IU):  {width}")
            print(f"  Width (mm):  {to_mm(width):.4f}")
            print(f"  Width (m):   {to_m(width):.6f}")
            print(f"  Layer:       {layer_name}")
            print(f"  Net:         '{net_name}'")

            if is_track and not is_via:
                selected_tracks_raw.append(item)

    print(f"\nTotal selected items: {selected_count}")
    print(f"Selected PCB_TRACKs (not vias): {len(selected_tracks_raw)}")

    # ── 3. Compat layer selection ──
    print("\n" + "-" * 70)
    print("  kicad_compat.get_selected_tracks() result:")
    print("-" * 70)

    from addon.kicad_compat import get_selected_tracks
    compat_tracks = get_selected_tracks(board)

    print(f"  Returned {len(compat_tracks)} TrackInfo objects")
    for i, t in enumerate(compat_tracks):
        print(f"\n  TrackInfo #{i+1}:")
        print(f"    start_x (IU): {t.start_x}")
        print(f"    start_y (IU): {t.start_y}")
        print(f"    end_x (IU):   {t.end_x}")
        print(f"    end_y (IU):   {t.end_y}")
        print(f"    width (IU):   {t.width}")
        print(f"    start (mm):   ({to_mm(t.start_x):.4f}, {to_mm(t.start_y):.4f})")
        print(f"    end (mm):     ({to_mm(t.end_x):.4f}, {to_mm(t.end_y):.4f})")
        print(f"    width (mm):   {to_mm(t.width):.4f}")
        print(f"    layer:        {t.layer_name}")
        print(f"    net:          '{t.net_name}'")

    # ── 4. Selection inference ──
    print("\n" + "-" * 70)
    print("  selection.infer_from_selection() result:")
    print("-" * 70)

    from addon.selection import infer_from_selection
    sel = infer_from_selection(board)

    print(f"  mode:            {sel.mode}")
    print(f"  valid:           {sel.valid}")
    print(f"  layer:           {sel.layer}")
    print(f"  net_name:        '{sel.net_name}'")
    print(f"  start_x_m:      {sel.start_x_m:.6f}  ({sel.start_x_m*1e3:.4f} mm)")
    print(f"  start_y_m:      {sel.start_y_m:.6f}  ({sel.start_y_m*1e3:.4f} mm)")
    print(f"  end_x_m:        {sel.end_x_m:.6f}  ({sel.end_x_m*1e3:.4f} mm)")
    print(f"  end_y_m:        {sel.end_y_m:.6f}  ({sel.end_y_m*1e3:.4f} mm)")
    print(f"  start_width_m:  {sel.start_width_m:.6f}  ({sel.start_width_m*1e3:.4f} mm)")
    print(f"  end_width_m:    {sel.end_width_m:.6f}  ({sel.end_width_m*1e3:.4f} mm)")
    print(f"  distance_m:     {sel.distance_m:.6f}  ({sel.distance_m*1e3:.2f} mm)")
    print(f"  start_tangent:  {sel.start_tangent_deg:.2f} deg")

    came_from_selection = sel.mode == "auto"
    print(f"\n  DATA SOURCE: {'LIVE SELECTED TRACKS' if came_from_selection else 'DEFAULTS / MANUAL'}")

    if sel.warnings:
        print(f"\n  WARNINGS:")
        for w in sel.warnings:
            print(f"    - {w}")
    if sel.info:
        print(f"\n  INFO:")
        for i in sel.info:
            print(f"    - {i}")

    print("\n" + "=" * 70)
    print("  DEBUG COMPLETE — no insertion performed")
    print("=" * 70)

    return sel


# Auto-run
sel = debug_selected_tracks()
