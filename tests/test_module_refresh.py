import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import module_refresh  # noqa: E402


class ModuleRefreshTests(unittest.TestCase):
    """Streamlit Cloud pulls new code into a running server; a view module
    imported before the pull must be reloaded on the next rerun."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        sys.path.insert(0, self.dir.name)
        self.addCleanup(sys.path.remove, self.dir.name)
        self.path = Path(self.dir.name) / "fake_view_for_refresh.py"
        self.addCleanup(sys.modules.pop, "fake_view_for_refresh", None)

    def write(self, value, bump=0):
        self.path.write_text(f"VALUE = {value!r}\n", encoding="utf-8")
        stamp = time.time() + bump
        os.utime(self.path, (stamp, stamp))

    def test_changed_modules_reload_and_unchanged_ones_do_not(self):
        names = ("fake_view_for_refresh",)
        self.write("old")
        import fake_view_for_refresh  # noqa: F401

        # Loaded before the guard existed (no stamp): reload once to be safe.
        self.assertEqual(module_refresh.refresh(names), ["fake_view_for_refresh"])
        self.assertEqual(module_refresh.refresh(names), [], "stamped and unchanged: no reload")

        # A pull rewrites the file: the next rerun picks up the new code.
        self.write("new", bump=5)
        self.assertEqual(module_refresh.refresh(names), ["fake_view_for_refresh"])
        self.assertEqual(sys.modules["fake_view_for_refresh"].VALUE, "new")
        self.assertEqual(module_refresh.refresh(names), [])

    def test_fresh_imports_are_stamped_without_a_reload(self):
        names = ("fake_view_for_refresh",)
        self.assertEqual(module_refresh.refresh(names), [], "not imported yet: nothing to do")
        self.write("fresh")
        import fake_view_for_refresh  # noqa: F401
        module_refresh.stamp(names)
        self.assertEqual(module_refresh.refresh(names), [])


if __name__ == "__main__":
    unittest.main()
