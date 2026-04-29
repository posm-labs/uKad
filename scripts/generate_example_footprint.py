"""Generate example Klopfenstein .kicad_mod footprints and print debug info.

Generates two examples:
  1. 50→75 Ω, Γm=0.05, f_start=1 GHz  (long, academic)
  2. 50→75 Ω, Γm=0.05, f_start=6 GHz  (realistic microwave)

Run:  python3 scripts/generate_example_footprint.py
"""

import sys, os, pathlib
_PROJECT_ROOT = '/Users/mahdi1265/uKad'
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from rfcore.taper_assembly import TaperAssembly
from addon.ui_main import synthesize_taper, SynthesisRequest
from addon.footprint_gen import (
    FootprintSpec, generate_footprint, generate_footprint_debug,
    save_footprint, footprint_dimensions, auto_footprint_name,
    default_library_path, library_registration_instructions,
)

out_dir = pathlib.Path(_PROJECT_ROOT) / "test_exports"
out_dir.mkdir(exist_ok=True)


def generate_example(ZS, ZL, Gamma_m, f_start, f_stop, label):
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")

    # Synthesize via full pipeline (validates RF core is used)
    settings = RFProjectSettings()
    settings.analysis.f_start_hz = f_start
    settings.analysis.f_stop_hz = f_stop

    request = SynthesisRequest(ZS_ohm=ZS, ZL_ohm=ZL, Gamma_m=Gamma_m)
    result, report, profile = synthesize_taper(request, settings)

    fp_name = auto_footprint_name(ZS, ZL, Gamma_m, f_start)

    spec = FootprintSpec(
        profile=profile, fp_name=fp_name,
        ZS=ZS, ZL=ZL, Gamma_m=Gamma_m,
        f_start_hz=f_start, f_stop_hz=f_stop,
    )

    # Generate both variants
    content_primary = generate_footprint(spec)
    content_debug = generate_footprint_debug(spec)
    dims = footprint_dimensions(spec)

    print(f"\n  ZS:           {ZS} Ω")
    print(f"  ZL:           {ZL} Ω")
    print(f"  Γm:           {Gamma_m}")
    print(f"  f_start:      {f_start/1e9:.1f} GHz")
    print(f"  f_stop:       {f_stop/1e9:.1f} GHz")
    print(f"\n  L_min:        {profile.L_min*1e3:.3f} mm")
    print(f"  L_body:       {dims['L_body_mm']:.3f} mm")
    print(f"  L_land_in:    {dims['L_landing_start_mm']:.3f} mm")
    print(f"  L_land_out:   {dims['L_landing_end_mm']:.3f} mm")
    print(f"  L_total:      {dims['L_total_mm']:.3f} mm")
    print(f"  w_start:      {dims['w_start_mm']:.4f} mm")
    print(f"  w_end:        {dims['w_end_mm']:.4f} mm")
    print(f"  Pad1 at x:    {dims['pad1_x_mm']:.3f} mm")
    print(f"  Pad2 at x:    {dims['pad2_x_mm']:.3f} mm")
    print(f"\n  Max |S11|:    {result.max_s11_db:.1f} dB")
    print(f"  Max |S22|:    {result.max_s22_db:.1f} dB")
    print(f"  Worst IL:     {result.max_insertion_loss_db:.2f} dB")
    print(f"  Port refs:    z01={result.z01:.0f}Ω, z02={result.z02:.0f}Ω")

    # Save
    fp1 = out_dir / f"{fp_name}.kicad_mod"
    fp1.write_text(content_primary)
    fp2 = out_dir / f"{fp_name}_debug.kicad_mod"
    fp2.write_text(content_debug)

    print(f"\n  Primary:  {fp1}")
    print(f"  Debug:    {fp2}")

    # Show first 20 lines of primary
    print(f"\n  Primary .kicad_mod (first 20 lines):")
    for line in content_primary.splitlines()[:20]:
        print(f"    {line}")
    print(f"    ... ({content_primary.count(chr(10))} total lines)")

    # Electrical connectivity notes
    print(f"\n  CONNECTIVITY NOTES:")
    print(f"    Primary variant: custom pad '1' + routing pad '1' (same net)")
    print(f"    → entire taper is one pad number → one net → DRC-correct")
    print(f"    → taper polygon is gr_poly primitive inside custom pad")
    print(f"    → all copper appears in Gerber export")
    print(f"    Debug variant: Pad '1' + Pad '2' + fp_poly (port-labeled)")
    print(f"    → use for visual debugging only")


# ── Example 1: Academic 1 GHz ──
generate_example(50, 75, 0.05, 1e9, 10e9, "Example 1: 50→75 Ω, 1 GHz (academic)")

# ── Example 2: Realistic 6 GHz ──
generate_example(50, 75, 0.05, 6e9, 20e9, "Example 2: 50→75 Ω, 6 GHz (realistic)")

# ── Library info ──
lib = default_library_path()
print(f"\n{'=' * 70}")
print(f"  Default library: {lib}")
print(f"\n{library_registration_instructions(lib)}")
print(f"{'=' * 70}")
