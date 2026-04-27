"""Debug: preview taper placement in board coordinates.

Uses the LIVE selection data, synthesizes a taper, and shows
exactly where the polygon would be placed — WITHOUT inserting.

Run in KiCad Scripting Console (after running debug_selected_tracks.py):
  exec(open('/Users/mahdi1265/uKad/scripts/debug_placement.py').read())

NOTE: Both selected tracks are 0.2mm (same width/impedance).
      For testing, we still use ZS=50, ZL=75 as explicit user overrides
      so there's an actual impedance taper to generate.
      In production, the user would enter ZS/ZL in the dialog.
"""

import sys
import os

_PROJECT_ROOT = '/Users/mahdi1265/uKad'
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Force reimport of all our modules to avoid stale cache
import importlib
import addon.kicad_compat
import addon.selection
import addon.live_insert
importlib.reload(addon.kicad_compat)
importlib.reload(addon.selection)
importlib.reload(addon.live_insert)


def debug_placement(ZS=50.0, ZL=75.0, Gamma_m=0.05, f_start=1e9, f_stop=10e9):
    """Preview placement without inserting."""
    print("\n" + "=" * 70)
    print("  DEBUG: Taper Placement Preview (NO INSERTION)")
    print("=" * 70)

    # ── 1. Read selection ──
    from addon.kicad_compat import get_board, to_mm
    from addon.selection import infer_from_selection

    board = get_board()
    sel = infer_from_selection(board)

    print(f"\n--- Selection ---")
    print(f"  Mode:       {sel.mode}")
    print(f"  Valid:      {sel.valid}")
    print(f"  Start:      ({sel.start_x_m*1e3:.4f}, {sel.start_y_m*1e3:.4f}) mm")
    print(f"  End:        ({sel.end_x_m*1e3:.4f}, {sel.end_y_m*1e3:.4f}) mm")
    print(f"  Gap:        {sel.distance_m*1e3:.2f} mm")
    print(f"  w_start:    {sel.start_width_m*1e3:.4f} mm")
    print(f"  w_end:      {sel.end_width_m*1e3:.4f} mm")
    print(f"  Tangent:    {sel.start_tangent_deg:.1f} deg")
    print(f"  Layer:      {sel.layer}")
    print(f"  Net:        '{sel.net_name}'")

    if not sel.valid:
        print("\n  ERROR: Selection not valid. Select exactly 2 tracks.")
        return None

    # ── 2. Synthesize taper ──
    print(f"\n--- RF Synthesis ---")
    print(f"  ZS = {ZS} ohm, ZL = {ZL} ohm")
    print(f"  Gamma_m = {Gamma_m}")
    print(f"  f_start = {f_start/1e9:.1f} GHz, f_stop = {f_stop/1e9:.1f} GHz")

    from addon.ui_main import synthesize_taper, SynthesisRequest
    from rfcore.config import RFProjectSettings

    settings = RFProjectSettings()
    settings.analysis.f_start_hz = f_start
    settings.analysis.f_stop_hz = f_stop
    settings.analysis.n_points = 21

    request = SynthesisRequest(ZS_ohm=ZS, ZL_ohm=ZL, Gamma_m=Gamma_m)
    result, report, profile = synthesize_taper(request, settings)

    print(f"  L_min:     {profile.L_min*1e3:.2f} mm")
    print(f"  L_actual:  {profile.L*1e3:.2f} mm")
    print(f"  w_start:   {profile.w_layout[0]*1e3:.4f} mm")
    print(f"  w_end:     {profile.w_layout[-1]*1e3:.4f} mm")
    print(f"  Max |S11|: {result.max_s11_db:.1f} dB")

    # ── 3. Prepare insertion plan ──
    print(f"\n--- Insertion Plan ---")
    from addon.live_insert import prepare_insertion

    plan = prepare_insertion(profile, sel, overlap_m=25e-6)

    print(f"  Anchor (start):     ({plan.start_xy_m[0]*1e3:.4f}, {plan.start_xy_m[1]*1e3:.4f}) mm")
    print(f"  Selected end:       ({plan.end_xy_m[0]*1e3:.4f}, {plan.end_xy_m[1]*1e3:.4f}) mm")
    print(f"  Predicted taper end:({plan.predicted_end_xy_m[0]*1e3:.4f}, {plan.predicted_end_xy_m[1]*1e3:.4f}) mm")
    print(f"  Tangent:            ({plan.tangent[0]:.4f}, {plan.tangent[1]:.4f})")
    print(f"  Normal:             ({plan.normal[0]:.4f}, {plan.normal[1]:.4f})")
    print(f"  L_gap:              {plan.L_gap_m*1e3:.2f} mm")
    print(f"  L_actual:           {plan.L_actual_m*1e3:.2f} mm")
    print(f"  Gap matches taper:  {plan.gap_matches}")
    print(f"  Connects start:     {plan.connects_start}")
    print(f"  Connects end:       {plan.connects_end}")

    # ── 4. Polygon debug ──
    poly = plan.polygon
    n = len(poly.outline)
    xs = [p[0]*1e3 for p in poly.outline]
    ys = [p[1]*1e3 for p in poly.outline]

    print(f"\n--- Polygon ({n} vertices) ---")
    print(f"  BBox X: [{min(xs):.4f}, {max(xs):.4f}] mm")
    print(f"  BBox Y: [{min(ys):.4f}, {max(ys):.4f}] mm")

    print(f"\n  First 5 vertices (mm):")
    for i in range(min(5, n)):
        print(f"    [{i}] ({poly.outline[i][0]*1e3:.4f}, {poly.outline[i][1]*1e3:.4f})")

    print(f"  Last 5 vertices (mm):")
    for i in range(max(0, n-5), n):
        print(f"    [{i}] ({poly.outline[i][0]*1e3:.4f}, {poly.outline[i][1]*1e3:.4f})")

    # ── 5. Sanity checks ──
    print(f"\n--- Sanity Checks ---")

    # Check: polygon starts near selected start
    first_left = poly.left_edge[0]
    first_right = poly.right_edge[0]
    start_cx = (first_left[0] + first_right[0]) / 2 * 1e3
    start_cy = (first_left[1] + first_right[1]) / 2 * 1e3
    sel_start_mm = (sel.start_x_m * 1e3, sel.start_y_m * 1e3)
    dist_start = ((start_cx - sel_start_mm[0])**2 + (start_cy - sel_start_mm[1])**2)**0.5

    print(f"  Polygon start center: ({start_cx:.4f}, {start_cy:.4f}) mm")
    print(f"  Selected start:       ({sel_start_mm[0]:.4f}, {sel_start_mm[1]:.4f}) mm")
    print(f"  Distance:             {dist_start:.4f} mm")
    ok_start = dist_start < 0.1  # within 100um
    print(f"  {'PASS' if ok_start else 'FAIL'}: polygon starts near selected start")

    # Check: polygon BBox is near board coordinates, not near origin
    bbox_near_origin = max(xs) < 10 and max(ys) < 10
    print(f"  {'FAIL - near origin!' if bbox_near_origin else 'PASS'}: polygon is in board coordinates (not at origin)")

    # Check: polygon extends in the correct direction
    sel_end_mm = (sel.end_x_m * 1e3, sel.end_y_m * 1e3)
    pred_end_mm = (plan.predicted_end_xy_m[0]*1e3, plan.predicted_end_xy_m[1]*1e3)
    print(f"  Predicted end:        ({pred_end_mm[0]:.4f}, {pred_end_mm[1]:.4f}) mm")
    print(f"  Selected end:         ({sel_end_mm[0]:.4f}, {sel_end_mm[1]:.4f}) mm")

    if plan.warnings:
        print(f"\n--- Warnings ---")
        for w in plan.warnings:
            print(f"  WARNING: {w}")
    if plan.info:
        print(f"\n--- Info ---")
        for i in plan.info:
            print(f"  INFO: {i}")

    print("\n" + "=" * 70)
    print("  PLACEMENT PREVIEW COMPLETE — no insertion performed")
    print("  To insert: insert_plan(board, plan)")
    print("=" * 70)

    return plan


def insert_plan(board, plan):
    """Insert a previously previewed plan."""
    import addon.board_insert
    importlib.reload(addon.board_insert)
    from addon.board_insert import insert_taper_zone, get_zone_uuid
    from addon.kicad_compat import refresh_board

    print("\n  Inserting...")
    zone = insert_taper_zone(
        board, plan.polygon,
        layer=plan.layer,
        net_name=plan.net_name,
    )
    uuid = get_zone_uuid(zone)
    print(f"  Zone UUID: {uuid}")
    refresh_board()
    print("  Done. Check canvas.")


# Auto-run
plan = debug_placement()
