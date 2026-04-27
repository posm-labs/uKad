# uKad
RF / microwave design tools for KiCad

uKad is a set of scripts and utilities for designing and validating RF PCB structures directly from KiCad layouts. The focus is on closing the gap between quick analytical design and full-wave EM results, without leaving a lightweight workflow.

This is not a general-purpose EDA tool. It targets specific pain points in RF layout: tapers, transitions, transmission lines, and passive structures where geometry and parasitics matter.

---

## Motivation

Typical RF workflow:
- derive dimensions (paper / MATLAB / ADS)
- redraw in PCB tool
- export to EM solver
- iterate manually

This is slow and error-prone, especially for small discontinuities (vias, tapers, launch regions) where layout details dominate.

uKad aims to:
- generate RF structures directly from layout context
- provide fast analytical estimates
- hook into EM simulation for validation
- make iteration cheap enough to actually use

---

## Current Scope

### Transmission lines
- microstrip / CPW impedance calculations
- effective permittivity and guided wavelength
- rough loss estimates

### Tapers and transitions
- impedance tapers (linear, exponential, Klopfenstein planned)
- SMA → microstrip transitions (geometry-driven, not idealized ports)
- investigation of nearby via effects (not just “perfect line” models)

### Passive structures (early)
- Wilkinson dividers
- filter primitives (hairpin / coupled-line work in progress)

---

## Design Approach

- Start from geometry, not ideal ports  
- Keep analytical models simple but physically meaningful  
- Treat discontinuities (vias, pads, launches) as first-class problems  
- Use EM simulation as a check, not the starting point  

The intent is not to replace ADS/HFSS, but to reduce how often you need them.

---

## Planned Features

- substrate/material database (RO4350B, etc.)
- better discontinuity models (via fences, pads, step changes)
- automated export to EM solvers (likely openEMS first)
- S-parameter visualization and comparison (analytic vs EM)
- KiCad plugin interface (select geometry → run tool)

---

## Example Direction

Target workflow:

1. select SMA footprint and attached trace in KiCad  
2. generate taper based on actual pad + trace geometry  
3. compute expected impedance profile and reflection  
4. run EM simulation on extracted geometry  
5. compare S11/S21 and adjust  

---

## Status

Early and incomplete. Expect:
- missing features
- changing APIs
- rough edges

---

## Contributing

Useful areas:
- transmission line / discontinuity modeling
- EM integration (openEMS or others)
- KiCad scripting / plugin interface
- microwave filter and coupler synthesis

---

## Notes

If you're doing RF in KiCad and constantly exporting to other tools just to answer simple questions, this project is meant to reduce that friction.
