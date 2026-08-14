from __future__ import annotations

from types import SimpleNamespace
import unittest

from ozon_app.detached_table_fix import FixedDetachedTableWindow, detached_filter_key


class _FakeWindow:
    def __init__(self) -> None:
        self.grab_released = 0
        self.withdrawn = 0
        self.destroyed = 0

    def grab_release(self) -> None:
        self.grab_released += 1

    def withdraw(self) -> None:
        self.withdrawn += 1

    def destroy(self) -> None:
        self.destroyed += 1


class DetachedTableFixTests(unittest.TestCase):
    def test_filter_key_matches_overview_and_scenario_tables(self) -> None:
        overview = object()
        scenario = object()
        other = object()
        owner = SimpleNamespace(overview_tree=overview, scenario_tree=scenario)

        self.assertEqual(detached_filter_key(owner, overview), "overview")
        self.assertEqual(detached_filter_key(owner, scenario), "scenario")
        self.assertIsNone(detached_filter_key(owner, other))

    def test_close_destroys_window_and_clears_controller_reference(self) -> None:
        detached = FixedDetachedTableWindow.__new__(FixedDetachedTableWindow)
        detached._closed = False
        detached.window = _FakeWindow()
        controller = SimpleNamespace(_detached=detached)
        detached.owner = SimpleNamespace(_table_modes={"overview": controller})

        detached.close()

        self.assertTrue(detached._closed)
        self.assertEqual(detached.window.grab_released, 1)
        self.assertEqual(detached.window.withdrawn, 1)
        self.assertEqual(detached.window.destroyed, 1)
        self.assertIsNone(controller._detached)

        detached.close()
        self.assertEqual(detached.window.destroyed, 1)


if __name__ == "__main__":
    unittest.main()
