"""KiCad ActionPlugin entry point for the Klopfenstein taper tool.

Registers the plugin in KiCad's toolbar. When activated:
  1. Reads the current board selection via ``addon.kicad_compat``
  2. Opens the wxPython taper dialog
  3. User configures RF params, previews S-parameters
  4. User clicks Insert → zone is placed on the board

Supported: KiCad 8 (primary), KiCad 9+ (future).

NOTE: This is the ONLY file that touches ``pcbnew`` directly — and
only for the ``ActionPlugin`` base class, which is the mandatory
registration mechanism.  All board operations go through
``addon.kicad_compat``.
"""

from __future__ import annotations

try:
    import pcbnew  # type: ignore — needed solely for ActionPlugin subclass

    class KlopfensteinTaperPlugin(pcbnew.ActionPlugin):
        """KiCad action plugin for Klopfenstein microstrip taper synthesis."""

        def defaults(self):
            self.name = "RF Klopfenstein Taper"
            self.category = "RF Tools"
            self.description = (
                "Synthesize and insert impedance-matched microstrip tapers. "
                "Select two tracks on the same copper layer, then run this plugin."
            )
            self.show_toolbar_button = True
            self.icon_file_name = ""  # TODO: add icon

        def Run(self):
            from addon.kicad_compat import (
                get_board,
                kicad_version,
                get_kicad_parent_window,
                refresh_board,
            )
            from addon.selection import infer_from_selection
            from addon.dialog import TaperDialog

            ver = kicad_version()
            board = get_board()
            selection = infer_from_selection(board)

            parent = get_kicad_parent_window()

            dlg = TaperDialog(
                parent, board=board, selection=selection,
                kicad_ver=ver,
            )
            dlg.ShowModal()
            dlg.Destroy()

            refresh_board()

    # Register the plugin
    KlopfensteinTaperPlugin().register()

except ImportError:
    # Not running inside KiCad — skip plugin registration
    pass
