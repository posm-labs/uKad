"""addon — KiCad plugin for Klopfenstein taper footprint generation.

KiCad discovers plugins by importing packages in its scripting/plugins
directory.  This __init__.py triggers plugin registration by importing
plugin_action, which defines and registers the ActionPlugin subclass.

Outside KiCad, the import is silently skipped.
"""

try:
    from addon import plugin_action  # noqa: F401 — triggers .register()
except Exception:
    pass  # Not running inside KiCad
