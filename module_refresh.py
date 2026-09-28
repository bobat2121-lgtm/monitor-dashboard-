"""Keep the app's own modules current on Streamlit Cloud.

Cloud pulls new commits into the running server and reruns the main script,
but modules the script imported stay cached from their first import, so a
change to a view module would otherwise wait for a reboot. The main script
calls `refresh` before its local imports and `stamp` after them.
"""
import importlib
import os
import sys

# Dependencies first: rules_view imports calibration_view lazily.
LOCAL_MODULES = ("dashboard_utils", "calibration_view", "grading_ui", "universe_view", "rules_view")


def _mtime(module):
    path = getattr(module, "__file__", None)
    try:
        return os.path.getmtime(path) if path else None
    except OSError:
        return None


def refresh(names=LOCAL_MODULES) -> list:
    """Reload every loaded module whose file changed since it was stamped, or
    that was never stamped (loaded before this guard existed)."""
    reloaded = []
    for name in names:
        module = sys.modules.get(name)
        mtime = _mtime(module) if module is not None else None
        if mtime is None or getattr(module, "__source_mtime__", None) == mtime:
            continue
        module = importlib.reload(module)
        module.__source_mtime__ = mtime
        reloaded.append(name)
    return reloaded


def stamp(names=LOCAL_MODULES) -> None:
    """Record the source time of modules imported fresh on this run."""
    for name in names:
        module = sys.modules.get(name)
        if module is not None and not hasattr(module, "__source_mtime__"):
            module.__source_mtime__ = _mtime(module)
