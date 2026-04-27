"""KiCad Scripting Console Integration Test.

Run this script inside KiCad's Tools > Scripting Console.

Prerequisites:
  - Open a board (.kicad_pcb) with at least two tracks on F.Cu
  - Select exactly two tracks on the same layer before running

Usage in KiCad Scripting Console:
  exec(open('/Users/mahdi1265/uKad/scripts/kicad_integration_test.py').read())

To insert the taper after dry run:
  test_zone_insertion(board, plan, dry_run=False)
"""

import sys
import os

# Add project root to path
_THIS_DIR = os.path.dirname(os.path.abspath(
    __file__ if '__file__' in dir() else '/Users/mahdi1265/uKad/scripts/kicad_integration_test.py'
))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
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
    print(f"  Major: {kicad_major()}")
    print(f"  Is KiCad 8: {is_kicad_8()}")
    print(f"  Is KiCad 9+: {is_kicad_9_or_later()}")

    board = get_board()
    fname = get_board_filename(board)
    print(f"  Board file: {fname}")

    return board


def test_selection(board):
    """Test 1: read current selection and infer endpoints."""
    print("\n" + "=" * 60)
    print("TEST 1: Selection Inference")
    print("=" * 60)

    from addon.selection import infer_from_selection

    result = infer_from_selection(board)

    print(f"  Mode: {result.mode}")
    print(f"  Valid: {result.valid}")
    print(f"  Layer: {result.layer}")
    print(f"  Net: {result.net_name}")
    print(f"  Start: ({result.start_x_m*1e3:.3f}, {result.start_y_m*1e3:.3f}) mm")
    print(f"  End:   ({result.end_x_m*1e3:.3f}, {result.end_y_m*1e3:.3f}) mm")
    print(f"  Start width: {result.start_width_m*1e3:.4f} mm")
    print(f"  End width:   {result.end_width_m*1e3:.4f} mm")
    print(f"  Distance:    {result.distance_m*1e3:.2f} mm")
    print(f"  Start tangent: {result.start_tangent_deg:.1f} deg")

    for w in result.warnings:
        print(f"  WARNING: {w}")
    for i in result.info:
        print(f"  INFO: {i}")

    return result


def test_synthesis():
    """Test 2: run taper synthesis with default params."""
    print("\n" + "=" * 60)
    print("TEST 2: Taper Synthesis (50 -> 75 ohm)")
    print("=" * 60)

    from addon.ui_main import synthesize_taper, SynthesisRequest
    from rfcore.config import RFProjectSettings

    settings = RFProjectSettings()
    settings.analysis.f_start_hz = 1e9
    settings.analysis.f_stop_hz = 10e9
    settings.analysis.n_points = 21

    request = SynthesisRequest(ZS_ohm=50.0, ZL_ohm=75.0, Gamma_m=0.05)
    result, report, profile = synthesize_taper(request, settings)

    print(f"  Max |S11|: {result.max_s11_db:.2f} dB")
    print(f"  Max |S22|: {result.max_s22_db:.2f} dB")
    print(f"  Worst IL:  {result.max_insertion_loss_db:.2f} dB")
    print(f"  z01={result.z01:.0f} ohm, z02={result.z02:.0f} ohm")
    print(f"  Length: {profile.L*1e3:.2f} mm")

    return result, profile


def test_placement(profile, selection):
    """Test 3: generate polygon in board coordinates."""
    print("\n" + "=" * 60)
    print("TEST 3: Board-Coordinate Placement")
    print("=" * 60)

    from addon.live_insert import prepare_insertion

    plan = prepare_insertion(profile, selection)

    print(plan.debug_summary())

    return plan


def test_zone_insertion(board, plan, dry_run=True):
    """Test 4: insert taper zone into active board.

    Call with dry_run=False to actually insert.
    """
    print("\n" + "=" * 60)
    label = "(DRY RUN)" if dry_run else "(LIVE INSERT)"
    print(f"TEST 4: Zone Insertion {label}")
    print("=" * 60)

    if dry_run:
        print("  Dry run -- not inserting.")
        print(f"  Would insert {len(plan.polygon.outline)} vertices on {plan.layer}")
        print(f"  Anchored at ({plan.start_xy_m[0]*1e3:.1f}, {plan.start_xy_m[1]*1e3:.1f}) mm")
        print(f"  Taper ends at ({plan.predicted_end_xy_m[0]*1e3:.1f}, {plan.predicted_end_xy_m[1]*1e3:.1f}) mm")
        print(f"  Connects start: {plan.connects_start}")
        print(f"  Connects end:   {plan.connects_end}")
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
    print(f"  Zone inserted successfully")
    print(f"  Zone UUID: {uuid}")

    refresh_board()
    print("  Board refreshed -- check the canvas")


# ── Run all tests ──

print("\n" + "=" * 60)
print("  KiCad RF Taper -- Integration Tests")
print("=" * 60)

board = test_compat_layer()
sel = test_selection(board)
result, profile = test_synthesis()
plan = test_placement(profile, sel)
test_zone_insertion(board, plan, dry_run=True)

print("\n" + "=" * 60)
print("ALL TESTS PASSED (zone insertion was dry run)")
print("To insert: test_zone_insertion(board, plan, dry_run=False)")
print("=" * 60)
