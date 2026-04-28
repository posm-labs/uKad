"""KiCad Scripting Console Integration Test (one-track launch mode).

Run in KiCad's Tools > Scripting Console:
  exec(open('/Users/mahdi1265/uKad/scripts/kicad_integration_test.py').read())

Prerequisites:
  - Open a board with at least one track on F.Cu
  - Select exactly ONE track before running

After dry run, to insert:
  insert_plan(get_board(), plan)
"""

import sys
import os

_PROJECT_ROOT = '/Users/mahdi1265/uKad'
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def test_compat_layer():
    """Test 0: kicad_compat version detection and board access."""
    print("=" * 60)
    print("TEST 0: Compatibility Layer")
    print("=" * 60)

    from addon.kicad_compat import (
        kicad_version, kicad_major, is_kicad_8, is_kicad_9_or_later,
        get_board, get_board_filename,
    )

    ver = kicad_version()
    print(f"  KiCad version: {ver[0]}.{ver[1]}.{ver[2]}")
    print(f"  Is KiCad 8: {is_kicad_8()}")

    board = get_board()
    print(f"  Board file: {get_board_filename(board)}")

    return board


def test_selection(board):
    """Test 1: one-track selection inference."""
    print("\n" + "=" * 60)
    print("TEST 1: One-Track Selection")
    print("=" * 60)

    from addon.selection import infer_from_selection

    sel = infer_from_selection(board)

    print(f"  Mode:     {sel.mode}")
    print(f"  Valid:    {sel.valid}")
    print(f"  Layer:    {sel.layer}")
    print(f"  Net:      '{sel.net_name}'")
    print(f"  Launch:   ({sel.launch_x_m*1e3:.4f}, {sel.launch_y_m*1e3:.4f}) mm")
    print(f"  Width:    {sel.track_width_m*1e3:.4f} mm")
    print(f"  Tangent:  {sel.launch_tangent_deg:.1f} deg")

    for w in sel.warnings:
        print(f"  WARNING: {w}")
    for i in sel.info:
        print(f"  INFO: {i}")

    return sel


def test_synthesis():
    """Test 2: taper synthesis."""
    print("\n" + "=" * 60)
    print("TEST 2: Taper Synthesis (50 -> 75 ohm)")
    print("=" * 60)

    from addon.ui_main import synthesize_taper, SynthesisRequest
    from rfcore.config import RFProjectSettings

    settings = RFProjectSettings()
    settings.analysis.f_start_hz = 1e9
    settings.analysis.f_stop_hz = 10e9

    request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)
    result, report, profile = synthesize_taper(request, settings)

    print(f"  L_body:    {profile.L*1e3:.2f} mm")
    print(f"  w_start:   {profile.w_layout[0]*1e3:.4f} mm")
    print(f"  w_end:     {profile.w_layout[-1]*1e3:.4f} mm")
    print(f"  Max |S11|: {result.max_s11_db:.1f} dB")

    return result, profile


def test_placement(profile, selection):
    """Test 3: composite polygon in board coordinates."""
    print("\n" + "=" * 60)
    print("TEST 3: Composite Launch Polygon")
    print("=" * 60)

    from addon.live_insert import prepare_insertion

    plan = prepare_insertion(profile, selection)
    print(plan.debug_summary())

    return plan


def test_zone_insertion(board, plan, dry_run=True):
    """Test 4: insert launch zone (dry run by default)."""
    print("\n" + "=" * 60)
    label = "(DRY RUN)" if dry_run else "(LIVE INSERT)"
    print(f"TEST 4: Zone Insertion {label}")
    print("=" * 60)

    if dry_run:
        print(f"  Would insert {len(plan.polygon.outline)} vertices on {plan.layer}")
        print(f"  Launch: ({plan.launch_xy_m[0]*1e3:.2f}, {plan.launch_xy_m[1]*1e3:.2f}) mm")
        print(f"  Output: ({plan.predicted_end_xy_m[0]*1e3:.2f}, {plan.predicted_end_xy_m[1]*1e3:.2f}) mm")
        print("  To insert: test_zone_insertion(board, plan, dry_run=False)")
        return

    from addon.board_insert import insert_taper_zone, get_zone_uuid
    from addon.kicad_compat import refresh_board

    zone = insert_taper_zone(
        board, plan.polygon,
        layer=plan.layer,
        net_name=plan.net_name,
    )
    uuid = get_zone_uuid(zone)
    print(f"  Zone UUID: {uuid}")
    refresh_board()
    print(f"  Done. Route next trace from: ({plan.predicted_end_xy_m[0]*1e3:.2f}, {plan.predicted_end_xy_m[1]*1e3:.2f}) mm")


# ── Run all tests ──
print("\n" + "=" * 60)
print("  Klopfenstein Launch — Integration Tests")
print("=" * 60)

board = test_compat_layer()
sel = test_selection(board)
result, profile = test_synthesis()
plan = test_placement(profile, sel)
test_zone_insertion(board, plan, dry_run=True)

print("\nTo insert: test_zone_insertion(board, plan, dry_run=False)")
