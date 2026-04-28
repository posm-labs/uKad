"""Debug: dump raw selected track data from KiCad (one-track mode).

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
    print("  DEBUG: Selected Track Data (one-trace launch mode)")
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

    for item in all_tracks:
        if not item.IsSelected():
            continue
        selected_count += 1

        type_name = type(item).__name__
        is_track = isinstance(item, pcbnew.PCB_TRACK)
        is_via = isinstance(item, pcbnew.PCB_VIA)

        start = item.GetStart()
        end = item.GetEnd()
        width = item.GetWidth()

        print(f"\n  --- Selected Item #{selected_count} ---")
        print(f"  Type:        {type_name}")
        print(f"  Is PCB_TRACK: {is_track}")
        print(f"  Is PCB_VIA:   {is_via}")
        print(f"  Start (IU):  ({start.x}, {start.y})")
        print(f"  Start (mm):  ({to_mm(start.x):.4f}, {to_mm(start.y):.4f})")
        print(f"  End (IU):    ({end.x}, {end.y})")
        print(f"  End (mm):    ({to_mm(end.x):.4f}, {to_mm(end.y):.4f})")
        print(f"  Width (IU):  {width}")
        print(f"  Width (mm):  {to_mm(width):.4f}")
        print(f"  Layer:       {item.GetLayerName()}")
        print(f"  Net:         '{item.GetNetname()}'")

    print(f"\nTotal selected items: {selected_count}")

    if selected_count == 0:
        print("\n  ⚠  No tracks selected! Select ONE input track.")
        return None

    if selected_count > 1:
        print(f"\n  ⚠  {selected_count} items selected. Select exactly 1 track.")
        print("     Using first track for inference.")

    # ── 3. Selection inference ──
    print("\n" + "-" * 70)
    print("  selection.infer_from_selection() result:")
    print("-" * 70)

    from addon.selection import infer_from_selection
    sel = infer_from_selection(board)

    print(f"  mode:          {sel.mode}")
    print(f"  valid:         {sel.valid}")
    print(f"  layer:         {sel.layer}")
    print(f"  net_name:      '{sel.net_name}'")
    print(f"  launch_x_m:   {sel.launch_x_m:.6f}  ({sel.launch_x_m*1e3:.4f} mm)")
    print(f"  launch_y_m:   {sel.launch_y_m:.6f}  ({sel.launch_y_m*1e3:.4f} mm)")
    print(f"  track_width:  {sel.track_width_m:.6f}  ({sel.track_width_m*1e3:.4f} mm)")
    print(f"  tangent:      {sel.launch_tangent_deg:.2f} deg")

    if sel.warnings:
        print(f"\n  WARNINGS:")
        for w in sel.warnings:
            print(f"    ⚠ {w}")
    if sel.info:
        print(f"\n  INFO:")
        for i in sel.info:
            print(f"    • {i}")

    print("\n" + "=" * 70)
    print("  DEBUG COMPLETE — no insertion performed")
    print("=" * 70)

    return sel


# Auto-run
sel = debug_selected_tracks()
