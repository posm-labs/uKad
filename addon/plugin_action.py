"""KiCad ActionPlugin entry point — Klopfenstein Taper Footprint Generator.

Registers the plugin in KiCad's PCB Editor toolbar.  When activated,
opens the footprint generator wizard dialog.

Entry point chain:
  KiCad imports addon/ package
  → addon/__init__.py imports addon.plugin_action (this file)
  → KlopfensteinTaperPlugin().register() is called
  → Plugin appears in: Tools → External Plugins → RF Klopfenstein Taper
  → And as a toolbar button (if show_toolbar_button = True)

Supported: KiCad 8 (primary), KiCad 9+ (future).

NOTE: This is the ONLY file that touches ``pcbnew`` directly — and
only for the ``ActionPlugin`` base class.  All other operations go
through ``addon.kicad_compat``.
"""

from __future__ import annotations

import os

try:
    import pcbnew  # type: ignore

    class KlopfensteinTaperPlugin(pcbnew.ActionPlugin):
        """KiCad action plugin for Klopfenstein microstrip taper synthesis."""

        def defaults(self):
            self.name = "RF Klopfenstein Taper"
            self.category = "RF Tools"
            self.description = (
                "Synthesize impedance-matched Klopfenstein microstrip tapers "
                "and generate .kicad_mod footprints."
            )
            self.show_toolbar_button = True

            # Icon: 24x24 PNG in the addon directory
            _dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(_dir, "icon_24.png")
            if os.path.exists(icon_path):
                self.icon_file_name = icon_path

        def Run(self):
            from addon.kicad_compat import kicad_version, get_kicad_parent_window
            from addon.dialog import TaperWizard

            ver = kicad_version()
            parent = get_kicad_parent_window()

            dlg = TaperWizard(parent, kicad_ver=ver)
            dlg.ShowModal()
            dlg.Destroy()

    # Register plugin — this makes it visible in KiCad's toolbar/menu
    KlopfensteinTaperPlugin().register()

except ImportError:
    pass  # Not running inside KiCad
