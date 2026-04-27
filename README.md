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
- microstrip impedance calculations
- effective permittivity and guided wavelength
- rough loss estimates

### Tapers and transitions
- impedance tapers (linear, exponential, Klopfenstein planned)
- SMA → microstrip transitions

---

## Assumptions (current)

Right now the models assume a standard 2-layer stackup:
- microstrip over solid ground plane  
- uniform substrate (RO4350B)  
- quasi-TEM propagation  

This keeps the analytical models fast and reasonably accurate. Layout-induced effects (vias, pads, launches) are handled separately or pushed to EM validation.

---

## References

Microstrip / transmission line models:
- Hammerstad & Jensen, *Accurate Models for Microstrip Computer-Aided Design*
- https://qucs.sourceforge.net/tech/node75.html
- https://qucs.sourceforge.net/docs/technical/technical.pdf

Effective dielectric constant (wide frequency validity):
- Kirschning & Jansen, *Accurate model for effective dielectric constant of microstrip with validity up to millimetre-wave frequencies*

Taper theory:
- R. W. Klopfenstein, *A Transmission Line Taper of Improved Design*
- https://www.microwaves101.com/encyclopedias/klopfenstein-taper
- https://eng.libretexts.org/Bookshelves/Electrical_Engineering/Electronics/Microwave_and_RF_Design_III_-_Networks_%28Steer%29/07%3A_Chapter_7/7.5%3A_Tapered_Matching_Transformers

Discontinuities / vias:
- Goldfarb & Pucel via model  
  https://qucs.sourceforge.net/tech/node83.html
- S-parameter modeling of microstrip discontinuities  
  https://www.researchgate.net/profile/Guenter-Kompa-2/publication/234324743_S-matrix_computation_of_microstrip_discontinuities_with_a_planar_waveguide_model/links/560cfbe908aea68653d38f74/S-matrix-computation-of-microstrip-discontinuities-with-a-planar-waveguide-model.pdf

Inductance calculations:
- Grover, *Inductance Calculations*

Substrate:
- Rogers RO4350B datasheet  
  https://www.rogerscorp.com/advanced-electronics-solutions/ro4000-series-laminates/ro4350b-laminates

EM backend:
- openEMS  
  https://openems.de
