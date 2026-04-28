"""Debug: preview one-trace Klopfenstein launch placement.

Uses LIVE selection, synthesizes a taper, shows where the composite
polygon would be placed — WITHOUT inserting.

Run in KiCad Scripting Console:
  exec(open('/Users/mahdi1265/uKad/scripts/debug_placement.py').read())
"""

import sys
import os

_PROJECT_ROOT = '/Users/mahdi1265/uKad'
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Force reimport
import importlib
import addon.kicad_compat
import addon.selection
import addon.live_insert
importlib.reload(addon.kicad_compat)
importlib.reload(addon.selection)
importlib.reload(addon.live_insert)


def debug_placement(ZS=50.0, ZL=75.0, Gamma_m=0.05, f_start=1e9, f_stop=10e9):
    """Preview one-trace launch placement without inserting."""
    print("\n" + "=" * 70)
    print("  DEBUG: One-Trace Klopfenstein Launch Preview (NO INSERTION)")
    print("=" * 70)

    # ── 1. Read selection ──
    from addon.kicad_compat import get_board
    from addon.selection import infer_from_selection

    board = get_board()
    sel = infer_from_selection(board)

    print(f"\n--- Selection ---")
    print(f"  Mode:       {sel.mode}")
    print(f"  Valid:      {sel.valid}")
    print(f"  Launch:     ({sel.launch_x_m*1e3:.4f}, {sel.launch_y_m*1e3:.4f}) mm")
    print(f"  Width:      {sel.track_width_m*1e3:.4f} mm")
    print(f"  Direction:  {sel.launch_tangent_deg:.1f} deg")
    print(f"  Layer:      {sel.layer}")
    print(f"  Net:        '{sel.net_name}'")

    if not sel.valid:
        print("\n  ERROR: Selection not valid. Select exactly 1 track.")
        return None

    # ── 2. Synthesize taper ──
    print(f"\n--- RF Synthesis ---")
    print(f"  ZS = {ZS} Ω, ZL = {ZL} Ω, Γm = {Gamma_m}")

    from addon.ui_main import synthesize_taper, SynthesisRequest
    from rfcore.config import RFProjectSettings

    settings = RFProjectSettings()
    settings.analysis.f_start_hz = f_start
    settings.analysis.f_stop_hz = f_stop
    settings.analysis.n_points = 21

    request = SynthesisRequest(ZS_ohm=ZS, ZL_ohm=ZL, Gamma_m=Gamma_m)
    result, report, profile = synthesize_taper(request, settings)

    print(f"  L_body:    {profile.L*1e3:.2f} mm")
    print(f"  w_start:   {profile.w_layout[0]*1e3:.4f} mm")
    print(f"  w_end:     {profile.w_layout[-1]*1e3:.4f} mm")
    print(f"  Max |S11|: {result.max_s11_db:.1f} dB")

    # ── 3. Prepare insertion plan ──
    from addon.live_insert import prepare_insertion

    plan = prepare_insertion(profile, sel)
    print(f"\n{plan.debug_summary()}")

    # ── 4. Sanity checks ──
    print(f"\n--- Sanity Checks ---")

    poly = plan.polygon
    n = len(poly.outline)
    xs = [p[0]*1e3 for p in poly.outline]
    ys = [p[1]*1e3 for p in poly.outline]

    # Check: polygon is near launch point, not at origin
    bbox_near_origin = max(abs(v) for v in xs + ys) < 10
    print(f"  {'FAIL - near origin!' if bbox_near_origin else 'PASS'}: polygon is in board coordinates")

    # Check: overlap extends backward from launch
    launch_mm = (sel.launch_x_m * 1e3, sel.launch_y_m * 1e3)
    print(f"  Launch:    ({launch_mm[0]:.2f}, {launch_mm[1]:.2f}) mm")
    print(f"  BBox X:    [{min(xs):.3f}, {max(xs):.3f}] mm")
    print(f"  BBox Y:    [{min(ys):.3f}, {max(ys):.3f}] mm")
    print(f"  Vertices:  {n}")

    # First/last vertices
    print(f"\n  First 3 vertices (mm):")
    for i in range(min(3, n)):
        print(f"    [{i}] ({poly.outline[i][0]*1e3:.4f}, {poly.outline[i][1]*1e3:.4f})")
    print(f"  Last 3 vertices (mm):")
    for i in range(max(0, n-3), n):
        print(f"    [{i}] ({poly.outline[i][0]*1e3:.4f}, {poly.outline[i][1]*1e3:.4f})")

    if plan.warnings:
        print(f"\n--- Warnings ---")
        for w in plan.warnings:
            print(f"  ⚠ {w}")

    print("\n" + "=" * 70)
    print("  PREVIEW COMPLETE — no insertion performed")
    print("  To insert: insert_plan(get_board(), plan)")
    print("=" * 70)

    return plan


def insert_plan(board, plan):
    """Insert a previously previewed plan."""
    import addon.board_insert
    importlib.reload(addon.board_insert)
    from addon.board_insert import insert_taper_zone, get_zone_uuid
    from addon.kicad_compat import refresh_board

    print("\n  Inserting zone...")
    zone = insert_taper_zone(
        board, plan.polygon,
        layer=plan.layer,
        net_name=plan.net_name,
    )
    uuid = get_zone_uuid(zone)
    print(f"  Zone UUID: {uuid}")
    refresh_board()
    print("  Done. Check canvas.")
    print(f"  Route next trace from: ({plan.predicted_end_xy_m[0]*1e3:.2f}, {plan.predicted_end_xy_m[1]*1e3:.2f}) mm")


# Auto-run
plan = debug_placement()
