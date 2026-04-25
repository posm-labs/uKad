# KiCad RF Tool v1: Klopfenstein Microstrip Taper

## Implementation Specification and Coding Brief for Claude

**Purpose:** this document is the handoff spec for the first RF convenience tool inside KiCad. It is intentionally narrow, specific, and implementation-oriented. Claude should treat this as the source of truth for architecture, algorithms, data structures, UI behavior, solver interfaces, optimization behavior, and acceptance tests.

**Project decision:** build one serious narrow tool first, not a generic RF suite. The tool synthesizes and inserts a lossy RO4350B microstrip Klopfenstein taper between two selected traces, computes a non-EM prediction for S11 and S21, models endpoint pads/vias/transitions as separate concatenated blocks, and optionally launches a slower `EM validate / EM optimize` path through a solver adapter whose first backend is openEMS.

## Hard constraints for v1

- KiCad-side integration must target the IPC API / addon direction, not legacy SWIG pcbnew scripting.
- Single line family only: top-layer microstrip above a continuous ground plane.
- Single laminate family only: RO4350B using project-stored stackup parameters.
- Single taper family only: Klopfenstein.
- The non-EM engine is mandatory and must be strong enough to be useful without any EM run.
- Pads, impedance steps, grounded vias, signal-via transitions, dielectric loss, conductor loss, and dispersion must be represented in v1 as separate model blocks concatenated with the taper body.
- Via fences / CPWG / arbitrary coupled-field environments are out of scope for v1, but the architecture must not block them later.
- The EM path must be optional, slower, and routed through a solver interface rather than hardcoded solver calls.

## 1. Product definition

**What we are building:** a KiCad addon plus a local RF engine service. The user selects two traces to connect. The tool reads the shared RF project settings (RO4350B stackup, copper thickness, design band, loss model choices, optimization defaults), synthesizes an ideal Klopfenstein impedance profile between the two trace impedances, inverts that profile into a width-versus-distance geometry, creates the taper copper, attaches endpoint discontinuity models, computes a fast circuit-model prediction, and optionally exports the exact local layout fragment for EM validation/optimization.

**What we are not building in v1:** full PCB SI extraction, multi-conductor coupled models, arbitrary launch synthesis, CPWG via-fence design, broad ADS replacement, arbitrary taper shapes, generic EM meshing UI, or a free-form optimization workbench.

## 2. User workflow

- User opens the addon and confirms or edits RF project settings once per board.
- User selects exactly two traces or one trace plus one target endpoint.
- Tool infers endpoint widths and centerline geometry.
- User enters design-band and matching target (either minimum frequency + max ripple / return-loss target, or a fixed taper length with the response predicted from it).
- Tool shows computed widths, taper length, predicted S11 and S21 from the non-EM engine, and any warnings.
- User clicks `Insert taper` to write copper to the board.
- Optional: user clicks `EM validate` or `EM optimize`. The addon exports a local fragment, the RF engine drives the configured solver adapter, and results are brought back into the UI.

## 3. Architecture

### Repository layout

```text
kicad-rf/
  addon/
    ipc_client.py              # KiCad IPC/addon-facing layer
    ui_main.py                 # minimal UI / forms / preview hooks
    board_extract.py           # reads selected traces, vias, pads, stackup refs
    board_insert.py            # writes taper geometry, annotations, metadata
  rfcore/
    config.py                  # project-level RF settings model
    materials_ro4350b.py       # laminate presets and validation
    microstrip.py              # Zc, eeff, alpha_d, alpha_c, beta
    klopfenstein.py            # profile generation and inverse design
    discontinuities/
      step.py                  # width step model
      pad.py                   # pad capacitance / flare block
      via_ground.py            # grounded via RL block
      via_signal.py            # signal-via transition block
      return_path.py           # optional return-via correction block
    network.py                 # ABCD/S conversion, cascading, slicing
    optimizer_fast.py          # non-EM optimizer
    optimizer_em.py            # low-budget EM optimization
    export/
      layout_fragment.py       # exact fragment extraction
      openems_adapter.py       # primary EM backend
      openparem2d_adapter.py   # future cross-section extraction / calibration
    cache.py
    reports.py
  tests/
    test_microstrip.py
    test_klopfenstein.py
    test_discontinuities.py
    test_network.py
    test_export.py
    golden/
```

**Implementation split:** the KiCad addon should stay thin. All RF mathematics, optimization, block models, export logic, and future solver adapters belong in `rfcore`. This is deliberate: it keeps the modeling code testable outside KiCad and reduces breakage from KiCad-side API changes.

## 4. Project-level RF settings (shared state)

### `RFProjectSettings`

```json
{
  "stackup": {
    "line_type": "microstrip",
    "laminate": "RO4350B",
    "substrate_height_m": "...",
    "copper_thickness_m": "...",
    "surface_roughness_m": "...",
    "dk_design": 3.48,
    "df_10ghz": 0.0037,
    "conductivity_s_per_m": 5.8e7,
    "ground_plane_continuous": true,
    "soldermask_present": false
  },
  "analysis": {
    "zref_ohm": 50.0,
    "f_start_hz": "...",
    "f_stop_hz": "...",
    "n_points": "...",
    "f_geometry_ref_hz": "...",
    "segmentation_tol": "...",
    "warn_if_electrically_short": true
  },
  "discontinuities": {
    "enable_step_model": true,
    "enable_pad_model": true,
    "enable_ground_via_model": true,
    "enable_signal_via_model": true,
    "enable_return_path_model": true
  },
  "em": {
    "backend": "openems",
    "capture_margin_m": "...",
    "port_extension_m": "...",
    "mesh_density_hint": "...",
    "max_em_evals": 12
  }
}
```

These settings live once per board / project, not per taper. Every future RF tool should read them.

## 5. Geometry object and source of truth

Source of truth must be an internal taper object, not only raw copper. After insertion, the addon should store a metadata blob (for example in board-level addon metadata or a sidecar file) containing the exact synthesized parameters and references to the attached endpoints. The copper is a rendered artifact of the taper object.

### `TaperObject`

```json
{
  "tool": "klopfenstein_microstrip_v1",
  "endpoint_a": {"...": "..."},
  "endpoint_b": {"...": "..."},
  "design": {
    "mode": "solve_length | fixed_length",
    "z_start_ohm": "...",
    "z_end_ohm": "...",
    "L_m": "...",
    "gamma_max": "...",
    "f_min_hz": "..."
  },
  "body_model": {"...": "..."},
  "discontinuity_chain_left": ["..."],
  "discontinuity_chain_right": ["..."],
  "results_fast": {"...": "..."},
  "results_em": {"...": "..."}
}
```

## 6. Exact modeling philosophy

The tool must never pretend that the taper body and the end discontinuities are the same thing. The non-EM engine therefore evaluates a cascaded two-port chain:

```text
Left endpoint chain -> taper body -> right endpoint chain
```

where each endpoint chain can contain, in order:

- ideal reference plane shift (if needed)
- width-step block
- pad block
- signal-via transition block
- return-path correction block
- grounded via shunt block(s) if explicitly connected

This separation is mandatory because it keeps later EM discrepancies interpretable: if EM differs from the fast model, we can ask whether the error is in the taper body, in the local line model, or in the discontinuity blocks.

## 7. Taper-body mathematics

### 7.1 Local line model

Use a serious microstrip model with the following quantities available at frequency `f` for a local width `w`:

- Characteristic impedance `Zc(w, f)`
- Effective dielectric constant `eeff(w, f)`
- Phase constant `beta(w, f)`
- Conductor attenuation `alpha_c(w, f)`
- Dielectric attenuation `alpha_d(w, f)`

Model stack for `microstrip.py`:

- Use a Hammerstad/Jensen-style base model for quasi-static `Zc` and effective dielectric constant.
- Apply conductor-thickness correction.
- Apply frequency-dependent dispersion correction for `eeff` and impedance.
- Apply conductor loss and dielectric loss corrections.
- Keep the API general enough that the line model can later be replaced or calibrated by OpenParEM2D.

### 7.2 Klopfenstein profile

The body profile is generated in impedance space, not by guessing a trace wedge. The implementation should compute the continuous characteristic-impedance profile `Z(z)` over `0 <= z <= L` using the standard Klopfenstein construction for source/load impedances and maximum passband reflection `Gamma_m`. The implementation may follow the classical formulation in Klopfenstein 1956 plus the known 1973 correction; scikit-rf and Steer are acceptable sanity references for the resulting profile shape.

**Required design inputs**

- `ZS` = start impedance
- `ZL` = end impedance
- `L` = physical taper length
- `Gamma_m` = specified maximum passband reflection coefficient
- `f_min` = minimum frequency of interest (used in warnings / solve-length mode)

**Solve-length mode:**

- solve for the smallest `L` meeting the target `Gamma_m` over the specified passband.

**Fixed-length mode:**

- treat `L` as given, compute the implied passband behavior and report whether the target is met.

The implementation detail that matters: the code must produce a continuous `Z(z)` profile sampled densely enough for subsequent inversion and network slicing. A uniform `z`-grid is acceptable initially, but the final chain used for S-parameter computation must support adaptive refinement.

### 7.3 Width inversion

The taper geometry is created by numerically inverting the local microstrip model at a reference geometry frequency `f_geometry_ref`:

For each sampled `z`:

- find `w(z)` such that `Zc(w(z), f_geometry_ref) = Z_target(z)`

This inversion must be numerical and monotonic. Use a bracketed 1D root solver or monotonic interpolation table over width. Do not use a closed-form inverse unless it is thoroughly unit-tested.

### 7.4 Nonuniform-line evaluation

The taper body is not evaluated by a single average impedance. It is evaluated as a cascade of many short lossy sections.

For each frequency `f`:

- partition `z` into adaptive slices
- for each slice `i`:
  - `w_i = representative width of slice`
  - `gamma_i(f) = alpha_i(f) + j*beta_i(f)`
  - `Zc_i(f) = local characteristic impedance`
  - build `ABCD_i` for a lossy transmission line section of length `dz_i`
- cascade all `ABCD_i`
- convert overall `ABCD` to S-parameters using `zref_ohm`

**Adaptive slicing rule:** refine where `|dZ/dz|` is large and where the local wavelength is short. The segmentation error target belongs in project settings. The body evaluator should cache local line-model queries aggressively because the optimizer will call it many times.

## 8. Endpoint discontinuity blocks

The following blocks must exist in v1. They may be enabled or disabled individually, but the default project should enable them.

### 8.1 Width-step block

**Purpose:** represent abrupt width transition between an existing selected trace and the start of the taper if they are not rendered as perfectly continuous. Use a microstrip impedance-step equivalent circuit. In the valid regime of the chosen formula, model this as a localized discontinuity with a shunt capacitance and the associated series-inductance partition used by the reference formula. Outside the validity window, warn and/or force the geometry generator to smooth the transition.

### 8.2 Pad block

**Purpose:** represent local capacitive loading caused by a trace entering a pad or widened flare region. v1 pad model must be explicit, not hand-waved away.

#### `PadBlock` parameters

```text
pad_shape                  # circular / square / rounded if available
pad_major_dim_m
pad_minor_dim_m
trace_width_in_m
trace_width_out_m
local_substrate_height_m
dk_design
attach_mode                # inline flare, via pad, component pad
```

**Equivalent:**

- primarily shunt capacitance `C_pad`
- optional short series inductive term if the reference formula requires it

**Project decision:** in v1, implement pads as local shunt-capacitance-dominated blocks parameterized by physical pad size and the trace widths entering/leaving the pad. If a via is present, the pad belongs to the signal-via transition block below rather than being modeled twice.

### 8.3 Grounded-via block

**Purpose:** represent an explicit shunt via to ground attached to the trace structure. For v1, use the classic microstrip grounded-via model as a series resistance plus inductance. This block only applies to vias intentionally connected to the local structure, not arbitrary nearby vias.

#### `GroundViaBlock` parameters

```text
via_drill_m
via_finished_diam_m
via_barrel_length_m
plating_thickness_m        # optional if available
conductivity_s_per_m
```

**Equivalent:**

- `Z_via_ground(f) = R_via(f) + j*omega*L_via`

Nearby but electrically unconnected vias are not folded into the grounded-via block. They are left to the EM path or future environment models.

### 8.4 Signal-via transition block

**Purpose:** represent a trace changing layers through a signal via near the taper endpoint. This is the most important transition model beyond the taper body itself.

#### `SignalViaTransitionBlock` parameters

```text
via_drill_m
via_finished_diam_m
pad_diam_top_m
antipad_diam_ref_m
transition_length_m
stub_length_m
entering_trace_width_m
exiting_trace_width_m
nearest_reference_planes
optional_return_via_distance_m
```

**Equivalent topology (v1):**

- series via inductance
- shunt pad / antipad capacitance
- optional open-stub section for unused via barrel
- optional return-path correction block if the reference plane changes

**Project decision:** the signal-via transition is a small cascaded subnetwork, not a single scalar parasitic. The model should explicitly expose series inductance, pad capacitance, and optional stub behavior. If the transition changes the reference plane, a return-path correction sub-block must be available.

### 8.5 Return-path correction block

**Purpose:** account for degradation when a layer transition forces return current to move between reference planes. v1 does not solve full cavity coupling analytically, but it must at least parameterize the intentional return-via distance when present and warn when absent.

- If the transition changes reference planes and a return via is identified, include a correction term / subnetwork parameterized by return-via distance.
- If no return via is identified, emit a high-severity warning and mark the fast model as lower-confidence.
- Do not silently assume perfect return current transfer across plane changes.

## 9. How to include nearby pads and vias in practice

The tool should not try to infer every via on the whole board. v1 must use a bounded capture rule.

### Capture rule v1

Automatically include:

- pads directly attached to the selected trace endpoints
- vias directly touching those pads/traces
- signal vias on the selected net within a configurable endpoint capture radius
- return vias explicitly tagged/identified as belonging to that transition

Do not automatically include:

- arbitrary nearby stitching fences
- distant unrelated vias
- broad-plane resonance effects

This keeps the non-EM engine deterministic and prevents false precision. The full local geometry, including nearby conductors within the export margin, will be included in the EM path.

## 10. Optimization

### 10.1 Fast non-EM optimizer

The fast optimizer should feel like a stripped-down ADS tuner/optimizer: small variable count, deterministic, and responsive. Use it by default before any EM run.

**Optimization variables (v1)**

- `L` — taper length
- `Gamma_m` or RL target
- `left_trim_m` — tiny smoothing/transition trim at left end
- `right_trim_m` — tiny smoothing/transition trim at right end
- optional capture-specific pad/via tuning vars if user enables them

**Objective:**

Minimize:

```text
J = w1*max_f |S11(f)| + w2*IL_penalty + w3*length_penalty + w4*manufacturing_penalty
```

**Recommended solver:**

- Stage A: global coarse search with `differential_evolution` over bounded vars
- Stage B: local refinement with `Powell`

The exact weight defaults should be user-visible but preset sensibly. The optimizer must cache all repeated line-model and network evaluations.

### 10.2 EM validate / EM optimize

The EM path is optional and slower. It always starts from the fast-model design rather than from scratch.

**EM Validate**

- export local layout fragment
- run solver backend
- read `S11` / `S21`
- compare against fast model
- store delta plots and summary metrics

**EM Optimize** (`v1.1` behavior acceptable)

- start from fast-model optimum
- vary only a very small bounded set of variables:
  - `L`
  - `left_trim_m`
  - `right_trim_m`
  - optional endpoint smoothing vars
- respect `max_em_evals` from settings
- objective is the same as fast optimizer but using EM S-parameters

**Project decision:** do not attempt arbitrary shape optimization in v1. Keep the design recognizably Klopfenstein and only allow a few local corrections around the ends.

## 11. EM backend choice

**Primary backend for the first implementation:** `openEMS`. Reason: it is a free 3D full-wave solver with Python-facing workflows and existing PCB-layout-oriented tooling around openEMS/gerber flows. This is a better fit for a button that takes a real KiCad layout fragment and returns 2-port S-parameters.

**Secondary / future backend:** `OpenParEM2D` for local cross-section extraction or calibration of the line model. `OpenParEM3D` can remain a future option, but it is not the first backend choice for the one-click layout-validation path.

## 12. EM export design

### `layout_fragment` export contract

**Inputs:**

- board path / IPC board handle
- taper object
- capture margin
- port extension length

**Output:**

Exact local sub-layout containing:

- signal copper in region
- reference plane copper in region
- included pads / vias in region
- stackup metadata
- port definitions
- net labels / trace IDs for debugging

**Important:** ports must not be defined exactly at the abrupt discontinuity. Extend each side by a small straight section where possible so the port reference plane is sane. If that cannot be done, warn the user that the EM result is more sensitive to port definition.

## 13. UI behavior

- Main pane shows: endpoint widths, inferred impedances, solved taper length, predicted return loss, insertion loss, warnings.
- Advanced pane shows: discontinuity blocks found and enabled, capture radius, pad/via parameters, segmentation controls.
- Buttons: `Preview`, `Insert Taper`, `Fast Optimize`, `EM Validate`, `EM Optimize`, `Export Report`.
- Warnings must be graded: info, warning, high-severity.
- A mismatch between fast and EM results larger than a configurable threshold should be highlighted and stored.

## 14. Concrete warnings the tool must emit

- Selected traces are not on the supported layer / supported microstrip configuration.
- Ground plane under the region is not continuous per tool assumptions.
- Width ratio or discontinuity parameter is outside the validity window of the selected closed-form model.
- Taper is electrically short relative to the requested low-end frequency.
- Reference plane changes but no intentional return via is detected.
- Via stub is long enough to plausibly matter in-band.
- Pad or via capture data is incomplete, so the transition block is degraded.
- Fast model and EM model disagree above the configured threshold.

## 15. Acceptance tests

Claude should not treat this as done until the following tests exist.

- Microstrip model sanity tests against known widths / impedances on RO4350B for several stackups.
- Klopfenstein profile tests: monotonic impedance transformation, endpoint match, symmetry properties where applicable, regression against scikit-rf or independently computed reference data.
- Network-cascade tests with analytically checkable short chains.
- Discontinuity-block tests that verify parameter extraction and block ordering.
- Round-trip geometry tests: selected endpoints -> taper object -> written copper -> re-read metadata.
- EM export smoke tests that produce a valid openEMS input package for at least one simple layout.

## 16. Build order (exact implementation sequence)

- Implement `RFProjectSettings` model and board-level persistence.
- Implement `RO4350B` material validation and microstrip line model.
- Implement Klopfenstein profile generation and width inversion.
- Implement body slicing + `ABCD` / `S` evaluation.
- Implement width-step, pad, grounded-via, and signal-via blocks.
- Implement endpoint capture / extraction logic from the board.
- Implement preview-only UI and report generation.
- Implement copper insertion.
- Implement fast optimizer.
- Implement openEMS export + EM validate.
- Implement limited EM optimize.

## 17. Non-negotiable coding rules for Claude

- Keep the modeling code pure and testable outside KiCad.
- No hidden global state; all settings must be explicit.
- Every block model must expose both parameters and its equivalent two-port construction.
- Every solver adapter must implement the same abstract interface.
- Use consistent SI units internally.
- Store exact generated taper metadata so designs are reproducible.
- Do not silently fall back to idealized behavior when transition data is missing; warn instead.

## 18. Sources and raw links

The following sources informed the scope and should be embedded directly in code comments / developer notes where relevant. Use the raw links below rather than indirect summaries.

- KiCad APIs and bindings (IPC API direction; SWIG deprecation notice)  
  https://dev-docs.kicad.org/en/apis-and-binding/
- KiCad PCB Python bindings deprecation page  
  https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/
- KiCad addons documentation  
  https://dev-docs.kicad.org/en/addons/
- openEMS introduction  
  https://docs.openems.de/intro.html
- gerber2ems GitHub repository  
  https://github.com/antmicro/gerber2ems
- OpenParEM main repository  
  https://github.com/OpenParEM/OpenParEM
- OpenParEM2D Users Manual  
  https://openparem.org/wp-content/uploads/2025/05/OpenParEM2D_Users_Manual.pdf
- OpenParEM3D Users Manual  
  https://openparem.org/wp-content/uploads/2025/05/OpenParEM3D_Users_Manual.pdf
- OpenParEM builder Users Manual  
  https://openparem.org/wp-content/uploads/2025/05/builder_Users_Manual.pdf
- Qucs technical papers index  
  https://qucs.sourceforge.net/tech/technical.html
- Qucs microstrip impedance step page  
  https://qucs.sourceforge.net/tech/node80.html
- Qucs microstrip via hole page  
  https://qucs.sourceforge.net/tech/node83.html
- Qucs technical PDF  
  https://qucs.sourceforge.net/docs/technical/technical.pdf
- Steer / LibreTexts tapered matching transformers  
  https://eng.libretexts.org/Bookshelves/Electrical_Engineering/Electronics/Microwave_and_RF_Design_III_-_Networks_%28Steer%29/07%3A_Chapter_7/7.5%3A_Tapered_Matching_Transformers
- scikit-rf Klopfenstein taper docs  
  https://scikit-rf.readthedocs.io/en/v1.8.0/api/generated/skrf.taper.Klopfenstein.html
- Rogers RO4350B product page  
  https://www.rogerscorp.com/advanced-electronics-solutions/ro4000-series-laminates/ro4350b-laminates
- Modeling of Via Interconnect through Pad in PCB (ACES Journal PDF)  
  https://aces-society.org/includes/downloadpaper.php?nf=19-5-21&of;=ACES_Journal_May_2019_Paper_21
- Return via connections for extending signal link path bandwidth of via transitions  
  https://www.researchgate.net/publication/224387068_Return_via_connections_for_extending_signal_link_path_bandwidth_of_via_transitions

## 19. Final one-paragraph instruction to Claude

Implement exactly the tool described above and do not broaden scope. Start with a thin KiCad IPC/addon layer and a standalone `rfcore` package. Use RO4350B-only microstrip, Klopfenstein-only taper synthesis, a strong non-EM engine based on a lossy dispersive nonuniform-line cascade, and separate concatenated discontinuity blocks for steps, pads, grounded vias, and signal-via transitions. Make openEMS the first EM backend behind an adapter interface. Persist project settings and taper metadata explicitly. Add tests before UI polish.
