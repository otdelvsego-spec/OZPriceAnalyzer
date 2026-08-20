from __future__ import annotations

from types import SimpleNamespace
import unittest

from ozon_app.shutdown_all_windows import close_detached_tables


class _Detached:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class ShutdownAllWindowsTests(unittest.TestCase):
    def test_close_detached_tables_closes_every_registered_window(self) -> None:
        first = _Detached()
        second = _Detached()
        owner = SimpleNamespace(
            _table_modes={
                "overview": SimpleNamespace(_detached=first),
                "scenario": SimpleNamespace(_detached=second),
                "catalog": SimpleNamespace(_detached=None),
            }
        )

        self.assertEqual(close_detached_tables(owner), 2)
        self.assertEqual(first.closed, 1)
        self.assertEqual(second.closed, 1)

    def test_close_detached_tables_tolerates_missing_modes(self) -> None:
        self.assertEqual(close_detached_tables(SimpleNamespace()), 0)


if __name__ == "__main__":
    unittest.main()
