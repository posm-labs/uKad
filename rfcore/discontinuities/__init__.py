"""Optional launch / transition discontinuity blocks.

These blocks model signal-path transitions such as signal vias, pads,
stubs, and return-path discontinuities.  They are NOT part of the
default same-layer Klopfenstein taper body — they are only included
when the user explicitly specifies a layer transition or launch.

For same-layer top microstrip tapers with continuous ground, no
transition blocks are needed.

Note: Nearby via fences and ground-stitching vias that do NOT carry
the RF signal are environmental effects, not signal-path transitions.
These are best handled by full-wave EM validation (future), not by
the lumped transition-block chain.
"""
