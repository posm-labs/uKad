"""KiCad ActionPlugin entry point — Klopfenstein Taper Footprint Generator.

Registers the plugin in KiCad's toolbar. When activated, opens the
footprint generator wizard dialog.

Supported: KiCad 8 (primary), KiCad 9+ (future).

NOTE: This is the ONLY file that touches ``pcbnew`` directly — and
only for the ``ActionPlugin`` base class.  All other operations go
through ``addon.kicad_compat``.
"""

from __future__ import annotations

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
            self.icon_file_name = ""  # TODO: add icon

        def Run(self):
            from addon.kicad_compat import kicad_version, get_kicad_parent_window
            from addon.dialog import TaperWizard

            ver = kicad_version()
            parent = get_kicad_parent_window()

            dlg = TaperWizard(parent, kicad_ver=ver)
            dlg.ShowModal()
            dlg.Destroy()

    # Register plugin
    KlopfensteinTaperPlugin().register()

except ImportError:
    pass  # Not running inside KiCad
