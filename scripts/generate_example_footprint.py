"""Generate an example .kicad_mod and print debug info.

Run standalone:
  cd /Users/mahdi1265/uKad && python3 scripts/generate_example_footprint.py

Or in KiCad scripting console:
  exec(open('/Users/mahdi1265/uKad/scripts/generate_example_footprint.py').read())
"""

import sys, os
_PROJECT_ROOT = '/Users/mahdi1265/uKad'
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from rfcore.config import RFProjectSettings
from rfcore.microstrip import MicrostripModel
from rfcore.klopfenstein import KlopfensteinProfile
from addon.footprint_gen import (
    FootprintSpec, generate_footprint, save_footprint,
    footprint_dimensions, auto_footprint_name, default_library_path,
    library_registration_instructions,
)

# ── Synthesize ──
settings = RFProjectSettings()
ms = MicrostripModel.from_settings(settings)

ZS, ZL, Gamma_m = 50.0, 75.0, 0.05
f_start = 1e9

profile = KlopfensteinProfile(
    ZS=ZS, ZL=ZL, Gamma_m=Gamma_m, microstrip=ms, f_min=f_start)

fp_name = auto_footprint_name(ZS, ZL, Gamma_m, f_start)

spec = FootprintSpec(
    profile=profile, fp_name=fp_name,
    ZS=ZS, ZL=ZL, Gamma_m=Gamma_m,
    f_start_hz=f_start, f_stop_hz=10e9,
)

# ── Generate ──
content = generate_footprint(spec)
dims = footprint_dimensions(spec)

print("=" * 60)
print("  Example Footprint Generation")
print("=" * 60)
print(f"\n  Name:       {fp_name}")
print(f"  ZS:         {ZS} Ω")
print(f"  ZL:         {ZL} Ω")
print(f"  Γm:         {Gamma_m}")
print(f"  f_start:    {f_start/1e9} GHz")
print(f"\n  L_body:     {dims['L_body_mm']:.3f} mm")
print(f"  L_land_s:   {dims['L_landing_start_mm']:.3f} mm")
print(f"  L_land_e:   {dims['L_landing_end_mm']:.3f} mm")
print(f"  L_total:    {dims['L_total_mm']:.3f} mm")
print(f"  w_start:    {dims['w_start_mm']:.4f} mm")
print(f"  w_end:      {dims['w_end_mm']:.4f} mm")
print(f"  Pad1 at x:  {dims['pad1_x_mm']:.3f} mm")
print(f"  Pad2 at x:  {dims['pad2_x_mm']:.3f} mm")

# ── Save ──
import pathlib
out_dir = pathlib.Path(_PROJECT_ROOT) / "test_exports"
out_dir.mkdir(exist_ok=True)
fp_path = out_dir / f"{fp_name}.kicad_mod"
fp_path.write_text(content)
print(f"\n  Saved to:   {fp_path}")

# ── Print first 30 lines ──
print(f"\n  .kicad_mod preview (first 30 lines):")
for i, line in enumerate(content.splitlines()[:30]):
    print(f"    {line}")
if content.count('\n') > 30:
    print(f"    ... ({content.count(chr(10))} total lines)")

# ── Default library info ──
lib = default_library_path()
print(f"\n  Default library: {lib}")
print(f"\n{library_registration_instructions(lib)}")
print("=" * 60)
